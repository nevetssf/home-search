// Criteria panel for the detail page: objective values (shared) + the current
// user's subjective rating sliders, plus the household weighted score.
// See PLAN.md §4 and backend services/scoring.py.
import { useEffect, useState } from 'react'
import { getPropertyCriteria, listCriteria, setCriterionValue } from '../api'

function valueFor(values, criterionId) {
  return values.find((v) => v.criterion_id === criterionId)
}

export default function CriteriaPanel({ propertyId }) {
  const [criteria, setCriteria] = useState([])
  const [data, setData] = useState(null)

  const load = async () => {
    const [crit, vals] = await Promise.all([
      listCriteria(),
      getPropertyCriteria(propertyId),
    ])
    setCriteria(crit)
    setData(vals)
  }

  useEffect(() => { load() }, [propertyId])

  const save = async (criterion, body) => {
    await setCriterionValue(propertyId, criterion.id, body)
    load()
  }

  if (!data) return <p>Loading criteria…</p>

  const objective = criteria.filter((c) => !c.is_subjective)
  const subjective = criteria.filter((c) => c.is_subjective)

  return (
    <div className="criteria-panel">
      <div className="score-header">
        <h3>Criteria</h3>
        {data.overall_score != null && (
          <span className="score">
            household score {(data.overall_score * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {objective.length > 0 && (
        <section>
          <h4>Objective</h4>
          {objective.map((c) => (
            <ObjectiveRow
              key={c.id} criterion={c}
              value={valueFor(data.objective, c.id)} onSave={save}
            />
          ))}
        </section>
      )}

      {subjective.length > 0 && (
        <section>
          <h4>My ratings</h4>
          {subjective.map((c) => (
            <RatingRow
              key={c.id} criterion={c}
              value={valueFor(data.my_ratings, c.id)}
              aggregate={data.aggregate_ratings[c.id]}
              onSave={save}
            />
          ))}
        </section>
      )}

      {criteria.length === 0 && (
        <p className="muted">No criteria defined yet — add some under “Criteria”.</p>
      )}
    </div>
  )
}

function ObjectiveRow({ criterion, value, onSave }) {
  const t = criterion.value_type
  if (t === 'boolean') {
    return (
      <label className="crow">
        <span>{criterion.name}</span>
        <input
          type="checkbox" checked={!!value?.value_bool}
          onChange={(e) => onSave(criterion, { value_bool: e.target.checked })}
        />
      </label>
    )
  }
  if (t === 'number') {
    return (
      <label className="crow">
        <span>{criterion.name}{criterion.unit ? ` (${criterion.unit})` : ''}</span>
        <input
          type="number" defaultValue={value?.value_number ?? ''}
          onBlur={(e) => e.target.value !== '' &&
            onSave(criterion, { value_number: Number(e.target.value) })}
        />
      </label>
    )
  }
  if (t === 'enum') {
    return (
      <label className="crow">
        <span>{criterion.name}</span>
        <select
          value={value?.value_text ?? ''}
          onChange={(e) => onSave(criterion, { value_text: e.target.value })}
        >
          <option value="">—</option>
          {(criterion.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
    )
  }
  return (
    <label className="crow">
      <span>{criterion.name}</span>
      <input
        type="text" defaultValue={value?.value_text ?? ''}
        onBlur={(e) => onSave(criterion, { value_text: e.target.value })}
      />
    </label>
  )
}

function RatingRow({ criterion, value, aggregate, onSave }) {
  const min = criterion.scale_min ?? 1
  const max = criterion.scale_max ?? 5
  const current = value?.value_number ?? min
  return (
    <label className="crow">
      <span>{criterion.name}</span>
      <span className="rating-control">
        <input
          type="range" min={min} max={max} value={current}
          onChange={(e) => onSave(criterion, { value_number: Number(e.target.value) })}
        />
        <b>{current}</b>
        {aggregate != null && (
          <small className="muted">avg {(aggregate * (max - min) + min).toFixed(1)}</small>
        )}
      </span>
    </label>
  )
}
