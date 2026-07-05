import type { Facility } from "./types";

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

export function FacilityCard({ facility }: { facility: Facility }) {
  const dir = directionsUrl(facility);
  const services = facility.services.slice(0, 6);
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
          {services.map((s) => (
            <li key={s}>{s}</li>
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
