export function RailSkeleton() {
  return (
    <div className="px-4 md:px-10" aria-hidden>
      <div className="mb-3 h-5 w-48 animate-pulse rounded bg-surface-2" />
      <div className="flex gap-4 overflow-hidden">
        {[0, 1, 2].map((i) => (
          <div key={i} className="aspect-video w-[78vw] shrink-0 animate-pulse rounded-md bg-surface sm:w-[calc((100vw-var(--sb))*0.46)] lg:w-[calc((100vw-var(--sb))*0.38)]" />
        ))}
      </div>
    </div>
  );
}

export function PageMessage({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-xl px-4 pt-40 text-center">
      <h1 className="font-display text-2xl font-bold">{title}</h1>
      {children && <div className="mt-3 text-sm text-muted">{children}</div>}
    </div>
  );
}