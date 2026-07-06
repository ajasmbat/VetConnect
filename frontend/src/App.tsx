import { useState } from "react";
import { askAssistant } from "./api";
import { FacilityCard } from "./FacilityCard";
import type { AssistantResponse } from "./types";

const EXAMPLES = [
  "Mental health near Los Angeles",
  "Cardiology in San Diego",
  "PTSD care near San Antonio",
  "Primary care in Houston",
  "Physical therapy in Seattle",
  "Optometry near Phoenix",
  "Dental care in Denver",
  "Emergency care in Chicago",
  "Audiology near Portland",
  "Pharmacy in Atlanta",
  "Women veteran care in Miami",
  "Nutrition in Nashville",
  "Homeless services in Detroit",
  "Cancer care near Cleveland",
  "Dermatology in Minneapolis",
  "Orthopedics in Philadelphia",
  "Podiatry near Tampa",
  "Urology in Dallas",
  "Neurology in New York",
  "Sleep medicine in Salt Lake City",
];

export default function App() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AssistantResponse | null>(null);

  async function submit(q: string) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    try {
      const res = await askAssistant(trimmed);
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="hero">
        <h1>VetConnect</h1>
        <p>Find VA facilities and services near you. Ask in plain English.</p>
      </header>

      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
      >
        <label htmlFor="q" className="sr-only">
          Your question
        </label>
        <input
          id="q"
          type="text"
          value={question}
          placeholder="e.g. Mental health near Los Angeles"
          onChange={(e) => setQuestion(e.target.value)}
          disabled={loading}
          autoFocus
        />
        <button type="submit" disabled={loading || !question.trim()}>
          {loading ? "Searching…" : "Ask"}
        </button>
      </form>

      <div className="examples" aria-label="Example searches">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            className="chip"
            disabled={loading}
            onClick={() => {
              setQuestion(ex);
              submit(ex);
            }}
          >
            {ex}
          </button>
        ))}
      </div>

      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      {result && (
        <section className="answer" aria-live="polite">
          <h2>Assistant</h2>
          <p>{result.answer}</p>
          {(result.parsed_service || result.parsed_location) && (
            <p className="meta">
              {result.parsed_service && (
                <>
                  <strong>Service:</strong> {result.parsed_service}
                </>
              )}
              {result.parsed_service && result.parsed_location && "  ·  "}
              {result.parsed_location && (
                <>
                  <strong>Location:</strong> {result.parsed_location}
                </>
              )}
            </p>
          )}
        </section>
      )}

      {result && result.facilities.length > 0 && (
        <section className="results" aria-label="Facilities">
          <h2>{result.facilities.length} facilities</h2>
          <div className="grid">
            {result.facilities.map((f) => (
              <FacilityCard
                key={f.id}
                facility={f}
                highlightService={result.parsed_service}
              />
            ))}
          </div>
        </section>
      )}

      {result && result.facilities.length === 0 && !error && (
        <p className="empty">
          No facilities matched. Try a nearby city or different service.
        </p>
      )}

      <footer className="foot">
        Public VA facility data only — no personal health information is
        collected or sent.
      </footer>
    </div>
  );
}
