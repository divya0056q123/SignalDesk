import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AuthGate from "./AuthGate";

const auth = vi.hoisted(() => ({
  fetchAuthStatus: vi.fn(),
  fetchCurrentUser: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
  requestEmailVerification: vi.fn(),
  requestPasswordReset: vi.fn(),
  completePasswordReset: vi.fn(),
  verifyEmail: vi.fn(),
  setAccountEmail: vi.fn(),
  unauthorizedEvent: "signaldesk:unauthorized",
}));

vi.mock("./api", () => ({
  UNAUTHORIZED_EVENT: auth.unauthorizedEvent,
  fetchAuthStatus: auth.fetchAuthStatus,
  fetchCurrentUser: auth.fetchCurrentUser,
  login: auth.login,
  logout: auth.logout,
  register: auth.register,
  requestEmailVerification: auth.requestEmailVerification,
  requestPasswordReset: auth.requestPasswordReset,
  completePasswordReset: auth.completePasswordReset,
  verifyEmail: auth.verifyEmail,
  setAccountEmail: auth.setAccountEmail,
}));

vi.mock("./App", () => ({
  default: ({ username, onSignOut }: { username?: string; onSignOut?: () => void }) => (
    <div>
      <span>{username}</span>
      <button onClick={onSignOut}>Sign out</button>
    </div>
  ),
}));

describe("AuthGate", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    auth.fetchCurrentUser.mockRejectedValue(new Error("Not signed in"));
    auth.logout.mockResolvedValue({ ok: true });
    auth.fetchAuthStatus.mockResolvedValue({
      auth_enabled: true,
      needs_setup: false,
      registration_open: true,
      setup_token_required: false,
      email_verification_required: false,
    });
    auth.requestPasswordReset.mockResolvedValue({
      message: "If the address is registered and verified, a recovery link has been sent.",
    });
  });

  it("registers an account with an email and asks the user to verify it", async () => {
    auth.register.mockResolvedValue({ username: "newuser", email_verification_sent: true });
    render(<AuthGate />);

    fireEvent.click(await screen.findByRole("button", { name: "New to Real-Time Log Analyzer? Create an account" }));
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "newuser" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "newuser@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "strong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Account created. Verify your email using the link we sent, then sign in.")).toBeTruthy();
    expect(auth.register).toHaveBeenCalledWith("newuser", "strong-password", "newuser@example.com", undefined);
    expect(auth.login).not.toHaveBeenCalled();
  });

  it("restores the cookie-authenticated username and signs out", async () => {
    auth.fetchCurrentUser.mockResolvedValue({
      username: "returning-user",
      email: "returning@example.com",
      email_verified: true,
    });
    render(<AuthGate />);

    expect(await screen.findByText("returning-user")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy());
    expect(auth.logout).toHaveBeenCalledOnce();
  });

  it("labels the email verification field on the dashboard", async () => {
    auth.fetchCurrentUser.mockResolvedValue({
      username: "returning-user",
      email: null,
      email_verified: false,
    });
    render(<AuthGate />);

    expect(await screen.findByText("Add a verified email for account recovery")).toBeTruthy();
    expect(screen.getByLabelText("Recovery email").getAttribute("placeholder")).toBe("you@example.com");
  });

  it("requests password recovery without revealing whether an email is registered", async () => {
    render(<AuthGate />);

    fireEvent.click(await screen.findByRole("button", { name: "Forgot password?" }));
    expect(screen.getByRole("heading", { name: "Recover your password" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "newuser@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send recovery link" }));

    expect(await screen.findByText("If the address is registered and verified, a recovery link has been sent.")).toBeTruthy();
    expect(auth.requestPasswordReset).toHaveBeenCalledWith("newuser@example.com");

    fireEvent.click(screen.getByRole("button", { name: "Back to sign in" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
  });
});
