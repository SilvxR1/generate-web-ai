import { useState } from "react";

const MIN_LENGTH = 10;
const MAX_LENGTH = 8000;

interface BriefingFormProps {
  onSubmit: (briefing: string) => void;
  isSubmitting: boolean;
}

export function BriefingForm({ onSubmit, isSubmitting }: BriefingFormProps) {
  const [briefing, setBriefing] = useState("");
  const trimmedLength = briefing.trim().length;
  const tooShort = trimmedLength > 0 && trimmedLength < MIN_LENGTH;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmedLength >= MIN_LENGTH) onSubmit(briefing.trim());
      }}
    >
      <label htmlFor="briefing" className="field-label">
        Describe your business
      </label>
      <textarea
        id="briefing"
        className="briefing-textarea"
        rows={10}
        maxLength={MAX_LENGTH}
        value={briefing}
        onChange={(event) => setBriefing(event.target.value)}
        placeholder={
          "Ej: Somos una peluquería en Valencia especializada en cortes clásicos, abierta desde 2015. " +
          "Atendemos por WhatsApp y queremos capturar leads desde la web..."
        }
        disabled={isSubmitting}
      />
      {tooShort && <p className="field-hint">Add a few more details (at least {MIN_LENGTH} characters).</p>}
      <button type="submit" disabled={isSubmitting || trimmedLength < MIN_LENGTH}>
        {isSubmitting ? "Analyzing…" : "Analyze business"}
      </button>
    </form>
  );
}
