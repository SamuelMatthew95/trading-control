interface LoadingStateProps {
  label?: string
}

export function LoadingState({ label = 'Loading…' }: LoadingStateProps) {
  return (
    <div className="flex min-h-28 items-center justify-center rounded-lg border border-slate-200 px-4 py-10 dark:border-slate-800">
      <p className="text-sm font-sans text-slate-500 dark:text-slate-400">{label}</p>
    </div>
  )
}
