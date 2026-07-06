import type { Facility } from "./types";

const MAX_VISIBLE_SERVICES = 6;

/**
 * A few canonical service keys don't naturally substring-match the VA's
 * current human-readable labels (e.g. "WomensHealth" vs "Women Veteran care").
 * These hints tell the frontend which raw labels to treat as "the match" so
 * we can promote them to the top of the list. Keep in sync with the backend
 * `SERVICE_ALIASES` when adding a new category.
 */
const EXTRA_LABEL_HINTS: Record<string, string[]> = {
  WomensHealth: ["gynecology", "women veteran"],
  Homelessness: ["homeless"],
  DentalServices: ["dental", "oral"],
  SubstanceUse: ["addiction", "substance"],
  Vaccines: ["vaccine", "immunization"],
  SmokingCessation: ["smoking", "tobacco"],
  CaregiverSupport: ["caregiver"],
  // Don't add generic "counseling" here — it also matches career, grief,
  // and family counseling, which are separate VA services.
  MentalHealthCare: ["mental health", "ptsd"],
  Cancer: ["cancer", "oncology"],
  // Don't hint "rehabilitation" — it substring-matches vocational-rehab
  // (a jobs benefit) and blind-rehab (an eye service).
  PhysicalTherapy: ["physical therapy", "occupational therapy", "physical medicine"],
};

/** Split CamelCase, collapse whitespace, lowercase. Mirrors backend `_normalize`.
 *  The two-step regex keeps runs of capitals together, so "PTSD care" stays
 *  "ptsd care" instead of "p t s d care". */
function normalize(s: string): string {
  return s
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")   // aB -> a B
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2") // ABc -> A Bc
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** True if `label` is a service the user asked for (loose substring match). */
function isMatch(label: string, highlight: string | null | undefined): boolean {
  if (!highlight) return false;
  const l = normalize(label);
  const h = normalize(highlight);
  if (l.includes(h) || h.includes(l)) return true;
  const hints = EXTRA_LABEL_HINTS[highlight] || [];
  return hints.some((hint) => l.includes(hint));
}

/**
 * Put the "matched" services first (in original order), then the rest,
 * then slice to the first N so the card stays compact.
 */
function orderServices(
  services: string[],
  highlight: string | null | undefined
): { label: string; matched: boolean }[] {
  const matched: string[] = [];
  const rest: string[] = [];
  for (const s of services) {
    (isMatch(s, highlight) ? matched : rest).push(s);
  }
  return [...matched, ...rest]
    .slice(0, MAX_VISIBLE_SERVICES)
    .map((label) => ({ label, matched: matched.includes(label) }));
}

function formatAddress(f: Facility): string {
  const { address_1, city, state, zip } = f.address;
  const line1 = address_1 ?? "";
  const line2 = [city, state].filter(Boolean).join(", ");
  return [line1, [line2, zip].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
}

function directionsUrl(f: Facility): string | null {
  if (f.lat == null || f.long == null) return null;
  return `https://www.google.com/maps/dir/?api=1&destination=${f.lat},${f.long}`;
}

export function FacilityCard({
  facility,
  highlightService,
}: {
  facility: Facility;
  highlightService?: string | null;
}) {
  const dir = directionsUrl(facility);
  const services = orderServices(facility.services, highlightService);
  return (
    <article className="card" aria-label={facility.name}>
      <header>
        <h3>{facility.name}</h3>
        {facility.classification && (
          <span className="tag">{facility.classification}</span>
        )}
      </header>
      <p className="addr">{formatAddress(facility) || "Address unavailable"}</p>
      {facility.phone && (
        <p className="phone">
          <a href={`tel:${facility.phone}`}>{facility.phone}</a>
        </p>
      )}
      {services.length > 0 && (
        <ul className="services" aria-label="Services offered">
          {services.map(({ label, matched }) => (
            <li key={label} className={matched ? "matched" : undefined}>
              {label}
            </li>
          ))}
        </ul>
      )}
      <div className="actions">
        {dir && (
          <a href={dir} target="_blank" rel="noreferrer" className="btn-link">
            Directions →
          </a>
        )}
        {facility.website && (
          <a
            href={facility.website}
            target="_blank"
            rel="noreferrer"
            className="btn-link"
          >
            Website →
          </a>
        )}
      </div>
    </article>
  );
}
