import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CopilotPage from "./CopilotPage";

const api = vi.hoisted(() => ({
  askEmailCopilot: vi.fn(),
}));

vi.mock("../services/api", () => api);

describe("Gmail Copilot", () => {
  beforeEach(() => api.askEmailCopilot.mockReset());
  afterEach(cleanup);

  it("shows grounded answers and source references", async () => {
    api.askEmailCopilot.mockResolvedValue({
      answer: "The meeting request asks for a reply.",
      sources: [{
        email_id: "email-1",
        subject: "Meeting request",
        sender: "Sender <sender@example.test>",
      }],
    });
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Copilot message"), {
      target: { value: "Which emails need a reply?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("The meeting request asks for a reply.")).toBeTruthy();
    expect(screen.getByLabelText("Source emails").textContent).toContain("Meeting request");
    expect(api.askEmailCopilot).toHaveBeenCalledWith({
      question: "Which emails need a reply?",
    });
  });

  it("shows a validation error without making a provider request", async () => {
    api.askEmailCopilot.mockResolvedValue({
      answer: "",
      sources: [],
    });
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Enter a question");
    expect(api.askEmailCopilot).not.toHaveBeenCalled();
  });

  it("shows a loading state while the answer is being generated", async () => {
    let resolveRequest!: (result: { answer: string; sources: [] }) => void;
    api.askEmailCopilot.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Copilot message"), {
      target: { value: "Summarize my important emails" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Checking relevant email context with Gemini…")).toBeTruthy();
    resolveRequest({ answer: "One email needs review.", sources: [] });
    expect(await screen.findByText("One email needs review.")).toBeTruthy();
  });
});
