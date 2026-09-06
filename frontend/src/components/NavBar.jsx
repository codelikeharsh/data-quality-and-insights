import { NavLink } from 'react-router-dom'

const linkClasses = ({ isActive }) =>
  `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? 'bg-slate-900 text-white'
      : 'text-slate-600 hover:bg-slate-200 hover:text-slate-900'
  }`

export default function NavBar() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold text-slate-900">
            Data Quality &amp; Insights Engine
          </span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
            works on any CSV/Excel
          </span>
        </div>
        <nav className="flex gap-1">
          <NavLink to="/" end className={linkClasses}>
            Upload
          </NavLink>
          <NavLink to="/dashboard" className={linkClasses}>
            Dashboard
          </NavLink>
        </nav>
      </div>
    </header>
  )
}
