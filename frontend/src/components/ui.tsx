import type { ButtonHTMLAttributes, ReactNode } from "react";

export function DemoNotice({ children = "Sample data · not connected to an account" }: { children?: ReactNode }) {
  return (
    <div className="demo-notice">
      <span className="size-1.5 rounded-full bg-amber-500" />
      {children}
    </div>
  );
}

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-accent">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-main sm:text-[28px]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Button({
  children,
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  return (
    <button
      className={`button button-${variant} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`surface-card ${className}`}>{children}</section>;
}
