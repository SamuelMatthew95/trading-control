import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
export function TerminalCard({ children, className }: { children: ReactNode; className?: string }) { return <section className={cn('rounded border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900', className)}>{children}</section> }
export function SectionHeader({ title, meta }: { title: string; meta?: ReactNode }) { return <header className="mb-2 flex items-center justify-between gap-2"><h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{title}</h2>{meta}</header> }
