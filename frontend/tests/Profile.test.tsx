import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getProfile } from "../src/api/client";
import { ProfilePage } from "../src/pages/Profile";
import type { Profile } from "../src/api/types";

vi.mock("../src/api/client", () => ({
  getProfile: vi.fn(),
  putProfile: vi.fn(),
  addMeasurement: vi.fn(),
  deleteMeasurement: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("ProfilePage", () => {
  it("shows a neutral loading state before the profile fetch resolves, not a premature first-run prompt", async () => {
    const { promise, resolve } = deferred<Profile>();
    vi.mocked(getProfile).mockReturnValue(promise);

    render(<ProfilePage />);

    // profile is still null while the fetch is pending — asserting "No
    // profile set up yet" here would be wrong for a user who has one.
    expect(screen.getByText(/loading profile/i)).toBeDefined();
    expect(screen.queryByText(/no profile set up yet/i)).toBeNull();

    resolve({ sex: "female", birthdate: "1985-01-01", measurements: [] });

    await waitFor(() => expect(screen.queryByText(/loading profile/i)).toBeNull());
    expect(screen.queryByText(/no profile set up yet/i)).toBeNull();
  });

  it("shows the first-run prompt once the fetch resolves 404 (no profile saved yet)", async () => {
    vi.mocked(getProfile).mockRejectedValue(new Error("404 Not Found: {}"));

    render(<ProfilePage />);

    await waitFor(() => expect(screen.getByText(/no profile set up yet/i)).toBeDefined());
  });
});
