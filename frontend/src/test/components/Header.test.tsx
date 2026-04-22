import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/theme/ThemeToggle", () => ({
  ThemeToggle: () => <button type="button">Theme</button>,
}));

import { Header } from "@/components/layout/Header";

describe("Header", () => {
  it("renders provided title", () => {
    render(<Header title="Trading Console" />);
    expect(screen.getByText(/trading console/i)).toBeInTheDocument();
  });

  it("renders subtitle when provided", () => {
    render(<Header title="Trading Console" subtitle="Live operations" />);
    expect(screen.getByText(/live operations/i)).toBeInTheDocument();
  });

  it("shows LIVE status indicator label", () => {
    render(<Header title="Trading Console" />);
    expect(screen.getByText(/live/i)).toBeInTheDocument();
  });

  it("renders theme toggle control", () => {
    render(<Header title="Trading Console" />);
    expect(screen.getByRole("button", { name: /theme/i })).toBeInTheDocument();
  });
});
