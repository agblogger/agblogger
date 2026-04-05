import type { BreakdownEntry } from '@/api/client'

interface BreakdownTableProps {
  title: string
  nameLabel: string
  entries: BreakdownEntry[]
}

export default function BreakdownTable({ title, nameLabel, entries }: BreakdownTableProps) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">{title}</h3>
      {entries.length === 0 ? (
        <p className="text-muted text-sm">No data.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-4 text-muted font-medium">{nameLabel}</th>
                <th className="text-right py-2 pr-4 text-muted font-medium">Visitors</th>
                <th className="text-right py-2 text-muted font-medium">%</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.name} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-ink">{e.name}</td>
                  <td className="py-2 pr-4 text-right text-ink">{e.count.toLocaleString()}</td>
                  <td className="py-2 text-right text-ink">{e.percent.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
