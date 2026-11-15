import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { LoaderCircle, Signal } from "lucide-react";
import App from "./App";
import {
  completePasswordReset, fetchAuthStatus, fetchCurrentUser, login, logout, register,
  requestEmailVerification, requestPasswordReset, setAccountEmail, UNAUTHORIZED_EVENT, verifyEmail,
} from "./api";
import type { AuthStatus } from "./api";

type RecoveryMode = "none" | "request" | "reset" | "verify" | "verify_request";

const initialUrl = new URLSearchParams(window.location.search);
const initialRecoveryToken = initialUrl.get("reset_password") ?? initialUrl.get("verify_email") ?? "";
const initialRecoveryMode: RecoveryMode = initialUrl.has("reset_password")
  ? "reset"
  : initialUrl.has("verify_email")
    ? "verify"
    : "none";

/** Shows the dashboard directly when auth is off; otherwise handles sign-in and account recovery. */
export default function AuthGate() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [authenticated, setAuthenticated] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [emailVerified, setEmailVerified] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [recoveryMode, setRecoveryMode] = useState<RecoveryMode>(initialRecoveryMode);
  const [recoveryToken, setRecoveryToken] = useState(initialRecoveryToken);
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [recoveryPassword, setRecoveryPassword] = useState("");
  const [password, setPassword] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");

  const loadStatus = useCallback(() => {
    setLoadError("");
    fetchAuthStatus().then(setStatus).catch(() => setLoadError("Cannot reach the log analyzer server."));
  }, []);

  useEffect(() => {
    loadStatus();
    if (initialRecoveryToken) window.history.replaceState({}, "", window.location.pathname);
  }, [loadStatus]);

  useEffect(() => {
    const onUnauthorized = () => {
      setAuthenticated(false);
      setUsername("");
      setEmailVerified(false);
      setError("Your session expired. Please sign in again.");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  useEffect(() => {
    if (!status) return;
    if (!status.auth_enabled) {
      setSessionLoading(false);
      return;
    }
    let active = true;
    setSessionLoading(true);
    fetchCurrentUser()
      .then((user) => {
        if (active) {
          setUsername(user.username);
          setEmail(user.email ?? "");
          setEmailVerified(user.email_verified);
          setAuthenticated(true);
        }
      })
      .catch(() => {
        if (active) {
          setAuthenticated(false);
          setUsername("");
          setEmail("");
          setEmailVerified(false);
        }
      })
      .finally(() => { if (active) setSessionLoading(false); });
    return () => { active = false; };
  }, [status?.auth_enabled]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const registering = status?.needs_setup || mode === "register";
      if (registering) {
        const result = await register(username, password, email, status?.setup_token_required ? setupToken : undefined);
        setNotice(result.email_verification_sent
          ? "Account created. Verify your email using the link we sent, then sign in."
          : "Account created, but no verification email was sent. Check the email settings or use Resend verification email.");
        setMode("login");
        setAuthenticated(false);
        setPassword("");
        setSetupToken("");
        setEmail("");
        loadStatus();
        return;
      }
      const session = await login(username, password);
      setAuthenticated(true);
      setUsername(session.username);
      setEmailVerified(session.email_verified);
      setPassword("");
      setSetupToken("");
      setSessionLoading(false);
      loadStatus();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function onRecoverySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setRecoveryNotice("");
    try {
      if (recoveryMode === "request") {
        const result = await requestPasswordReset(recoveryEmail);
        setRecoveryNotice(result.message ?? "If the address is registered and verified, a recovery link has been sent.");
        setRecoveryEmail("");
      } else if (recoveryMode === "verify_request") {
        const result = await requestEmailVerification(recoveryEmail);
        setRecoveryNotice(result.message ?? "If an unverified account uses that address, a verification link has been sent.");
        setRecoveryEmail("");
      } else if (recoveryMode === "reset") {
        await completePasswordReset(recoveryToken, recoveryPassword);
        setRecoveryPassword("");
        setRecoveryToken("");
        setRecoveryMode("none");
        setNotice("Password reset. Sign in using your new password.");
      } else if (recoveryMode === "verify") {
        await verifyEmail(recoveryToken);
        setRecoveryToken("");
        setRecoveryMode("none");
        setNotice("Email verified. You can now sign in.");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The request could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  async function onSetEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await setAccountEmail(email);
      setNotice("Verification email sent. Open its link to enable password recovery.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send verification email.");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    try {
      await logout();
    } catch {
      setError("Could not confirm sign-out with the server. Please try again.");
      return;
    }
    setAuthenticated(false);
    setUsername("");
    setEmail("");
    setEmailVerified(false);
    setError("");
    setNotice("");
    setMode("login");
  }

  if (loadError) return <div className="auth-screen"><div className="auth-card"><p>{loadError}</p><button className="button button-primary" onClick={loadStatus}>Retry</button></div></div>;
  if (!status) return <div className="auth-screen"><LoaderCircle className="spin" size={22} /></div>;
  if (!status.auth_enabled) return <App />;
  if (sessionLoading) return <div className="auth-screen"><LoaderCircle className="spin" size={22} /></div>;

  if (recoveryMode !== "none") return (
    <div className="auth-screen">
      <form className="auth-card recovery-card" onSubmit={(event) => void onRecoverySubmit(event)}>
        <div className="auth-logo"><Signal size={20} /> Real-Time Log Analyzer</div>
        <h1>{recoveryMode === "request" ? "Recover your password" : recoveryMode === "reset" ? "Choose a new password" : recoveryMode === "verify_request" ? "Resend verification email" : "Verify your email"}</h1>
        {(recoveryMode === "request" || recoveryMode === "verify_request") && <>
          <p>{recoveryMode === "request"
            ? "Enter your verified account email. If it matches an account, we will send a short-lived recovery link."
            : "Enter the address used during registration. If it belongs to an unverified account, we will send a verification link."}</p>
          <label>Email<input required type="email" autoComplete="email" maxLength={254} value={recoveryEmail} onChange={(event) => setRecoveryEmail(event.target.value)} /></label>
        </>}
        {recoveryMode === "reset" && <>
          <p>Choose a new password. This recovery link can only be used once.</p>
          <label>New password<input required type="password" minLength={8} maxLength={128} autoComplete="new-password" value={recoveryPassword} onChange={(event) => setRecoveryPassword(event.target.value)} /></label>
        </>}
        {recoveryMode === "verify" && <p>Continue to confirm the email address associated with this account.</p>}
        {error && <div className="auth-error" role="alert">{error}</div>}
        {recoveryNotice && <div className="auth-notice" role="status">{recoveryNotice}</div>}
        <button className="button button-primary" type="submit" disabled={busy}>
          {busy ? <LoaderCircle className="spin" size={15} /> : null}
          {recoveryMode === "request" ? "Send recovery link" : recoveryMode === "reset" ? "Reset password" : recoveryMode === "verify_request" ? "Send verification link" : "Verify email"}
        </button>
        <button className="auth-switch" type="button" onClick={() => { setRecoveryMode("none"); setError(""); setRecoveryNotice(""); }}>Back to sign in</button>
      </form>
    </div>
  );

  if (authenticated) return (
    <div className={!emailVerified ? "account-email-layout" : undefined}>
      {!emailVerified && (
        <form className="account-email-panel" onSubmit={(event) => void onSetEmail(event)}>
          <div>
            <strong>Add a verified email for account recovery</strong>
            <p>Enter your email address and we’ll send a verification link.</p>
          </div>
          <label className="account-email-field">
            Recovery email
            <input
              required
              type="email"
              autoComplete="email"
              maxLength={254}
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <button className="button button-secondary" type="submit" disabled={busy}>
            {busy ? "Sending…" : "Send verification"}
          </button>
          {error && <span className="auth-error" role="alert">{error}</span>}
          {notice && <span className="auth-notice" role="status">{notice}</span>}
        </form>
      )}
      <App username={username} onSignOut={() => { void signOut(); }} />
    </div>
  );

  const setup = status.needs_setup;
  const registering = setup || mode === "register";
  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={(event) => void onSubmit(event)}>
        <div className="auth-logo"><Signal size={20} /> Real-Time Log Analyzer</div>
        <h1>{setup ? "Create the first account" : registering ? "Create your account" : "Sign in"}</h1>
        <p>{setup
          ? status.setup_token_required
            ? "Enter the one-time deployment setup code to create the first account. Your logs and alert rules are private to your account."
            : "Set up your account to get started. Your logs and alert rules are private to your account."
          : registering
            ? "Create an account with a private log analyzer workspace."
            : "Enter your credentials to open your private dashboard."}</p>
        <label>Username<input required minLength={3} maxLength={40} autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        {registering && <label>Email<input required type="email" maxLength={254} autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>}
        <label>Password<input required type="password" minLength={8} maxLength={128} autoComplete={registering ? "new-password" : "current-password"} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {setup && status.setup_token_required && <label>Setup code<input required type="password" autoComplete="one-time-code" value={setupToken} onChange={(event) => setSetupToken(event.target.value)} /></label>}
        {error && <div className="auth-error" role="alert">{error}</div>}
        {notice && <div className="auth-notice" role="status">{notice}</div>}
        <button className="button button-primary" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : null}{registering ? "Create account" : "Sign in"}</button>
        {!setup && !registering && <button className="auth-switch" type="button" onClick={() => { setRecoveryMode("request"); setError(""); setRecoveryNotice(""); setNotice(""); }}>Forgot password?</button>}
        {!setup && !registering && status.email_verification_required && <button className="auth-switch" type="button" onClick={() => { setRecoveryMode("verify_request"); setError(""); setRecoveryNotice(""); setNotice(""); }}>Resend verification email</button>}
        {!setup && status.registration_open && <button
          className="auth-switch"
          type="button"
          onClick={() => { setMode(registering ? "login" : "register"); setError(""); setNotice(""); }}
        >{registering ? "Already have an account? Sign in" : "New to Real-Time Log Analyzer? Create an account"}</button>}
      </form>
    </div>
  );
}
