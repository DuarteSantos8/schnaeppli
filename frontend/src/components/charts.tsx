/** Small, honest SVG charts: one series in ink, the current period in the data hue. */

export function Bars({
  data,
  format,
  highlightLast = true,
  height = 160,
  label,
}: {
  data: { key: string; label: string; value: number }[];
  format: (v: number) => string;
  highlightLast?: boolean;
  height?: number;
  label: string;
}) {
  if (data.length === 0) return <p className="text-sm text-muted">No data for this period.</p>;
  const max = Math.max(...data.map((d) => d.value), 0);
  const top = niceCeil(max || 1);
  const w = 100 / data.length;
  const ticks = [0, top / 2, top];
  const step = Math.ceil(data.length / 6);
  return (
    <figure aria-label={label}>
      <div className="flex gap-2">
        <div className="num flex flex-col justify-between pb-5 text-right text-[0.6875rem] text-muted" style={{ height }} aria-hidden>
          {[...ticks].reverse().map((t) => <span key={t}>{format(t)}</span>)}
        </div>
        <div className="min-w-0 flex-1">
          <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full" style={{ height: height - 20 }} role="img" aria-label={label}>
            {ticks.map((t) => (
              <line key={t} x1="0" x2="100" y1={(height - 20) * (1 - t / top)} y2={(height - 20) * (1 - t / top)} stroke="var(--color-rule)" strokeDasharray="1.5 1.5" vectorEffect="non-scaling-stroke" />
            ))}
            {data.map((d, i) => {
              const h = ((height - 20) * d.value) / top;
              const last = highlightLast && i === data.length - 1;
              return (
                <rect key={d.key} x={i * w + w * 0.18} width={w * 0.64} y={height - 20 - h} height={Math.max(h, d.value > 0 ? 1 : 0)} rx="0.6" fill={last ? "var(--color-score)" : "var(--color-ink)"}>
                  <title>{`${d.label}: ${format(d.value)}`}</title>
                </rect>
              );
            })}
          </svg>
          <div className="num relative mt-1 h-4 text-[0.6875rem] text-muted" aria-hidden>
            {data.map((d, i) =>
              i % step === 0 || i === data.length - 1 ? (
                <span key={d.key} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${(i + 0.5) * w}%` }}>
                  {d.label}
                </span>
              ) : null,
            )}
          </div>
        </div>
      </div>
      <table className="sr-only">
        <tbody>
          {data.map((d) => (
            <tr key={d.key}><td>{d.label}</td><td>{format(d.value)}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function niceCeil(v: number) {
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / exp;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return nice * exp;
}

/** A single horizontal meter: filled parts in order, rest empty. */
export function Meter({ parts, total, label }: { parts: { value: number; color: string; label: string }[]; total: number; label: string }) {
  const safe = Math.max(total, parts.reduce((s, p) => s + p.value, 0), 1);
  return (
    <div role="img" aria-label={label} className="flex h-2 overflow-hidden rounded-full bg-raised">
      {parts.map((p) => (
        <div key={p.label} title={p.label} style={{ width: `${(p.value / safe) * 100}%`, background: p.color }} />
      ))}
    </div>
  );
}
