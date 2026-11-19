import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Order = { id: string; patient: string; mrn: string; medication: string; status: string; attempts: number; error: string; plan: string };
const empty = { patient_first_name: '', patient_last_name: '', patient_mrn: '', patient_date_of_birth: '', primary_diagnosis_code: '', medication_name: '', provider_name: '', provider_npi: '', patient_records: '', medication_history: '', additional_diagnoses: '' };
const fields: { key: keyof typeof empty; label: string; pattern?: string; type?: string }[] = [
  {key:'patient_first_name',label:'First name'}, {key:'patient_last_name',label:'Last name'},
  {key:'patient_mrn',label:'MRN',pattern:'[0-9]{6}'}, {key:'patient_date_of_birth',label:'Date of birth',type:'date'},
  {key:'primary_diagnosis_code',label:'Primary diagnosis (ICD-10)'}, {key:'medication_name',label:'Medication'},
  {key:'provider_name',label:'Provider name'}, {key:'provider_npi',label:'Provider NPI',pattern:'[0-9]{10}'},
];

function App() {
  const [form, setForm] = useState(empty);
  const [orders, setOrders] = useState<Order[]>([]);
  const [selected, setSelected] = useState('');
  const [csrf, setCsrf] = useState('');
  const [mode, setMode] = useState('');
  const [error, setError] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const active = orders.find(order => order.id === selected);

  useEffect(() => {
    let stopped = false;
    async function refresh() {
      try {
        const response = await fetch('/api/orders');
        if (!response.ok) throw Error('Could not load orders.');
        const data = await response.json();
        if (!stopped) setOrders(data.orders);
      } catch {
        if (!stopped) setError('Connection lost. Check that the API is running.');
      }
    }
    fetch('/api/health').then(r => r.json()).then(data => { setCsrf(data.csrf); setMode(data.mode); }).catch(() => setError('Could not connect to the API.'));
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/orders', {
        method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':csrf},
        body:JSON.stringify({...form, confirm_warnings:warnings.length > 0}),
      });
      const data = await response.json();
      if (data.warnings) { setWarnings(data.warnings); return; }
      if (!response.ok) throw Error(data.error || 'Could not submit the order.');
      setOrders(current => [data, ...current]); setSelected(data.id); setWarnings([]);
    } catch (error) { setError(error instanceof Error ? error.message : 'Submission failed.'); }
    finally { setBusy(false); }
  }

  async function retry(order: Order) {
    setError(''); setBusy(true);
    try {
      const response = await fetch('/api/orders/' + order.id + '/retry', {method:'POST', headers:{'X-CSRFToken':csrf}});
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      setOrders(current => current.map(item => item.id === order.id ? result : item));
    } catch (error) { setError(error instanceof Error ? error.message : 'Retry failed.'); }
    finally { setBusy(false); }
  }

  function sample() {
    setWarnings([]);
    setForm({...empty, patient_first_name:'Alex', patient_last_name:'Example', patient_mrn:String(Math.floor(100000+Math.random()*900000)), patient_date_of_birth:'1990-01-01', primary_diagnosis_code:'Z00.00', medication_name:'Example medication', provider_name:'Demo Provider', provider_npi:'0000000000', patient_records:'Synthetic fixture for a portfolio demonstration.'});
  }

  return <div className="workspace">
    <header><a className="brand" href="/">careplan<span> / draft workspace</span></a><a href="/api/orders/export">Export orders ↓</a></header>
    <main>
      <div className="intro"><p className="eyebrow">ORDER TO DRAFT</p><h1>Less paperwork.<br />More time to review.</h1><p>Enter an order, track generation, and download a draft for pharmacist review.</p></div>
      <p className="notice">{mode === 'demo' ? 'Synthetic demo · Template generation · Use fictional patient data.' : 'Claude mode · External generation · Pharmacist review required.'}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="columns">
        <section aria-labelledby="intake-title"><div className="section-head"><h2 id="intake-title">New order</h2><button type="button" className="quiet" onClick={sample}>Fill sample</button></div>
          <form onSubmit={submit}>
            <div className="fields">{fields.map(field => <label key={field.key}>{field.label}<input required type={field.type || 'text'} pattern={field.pattern} maxLength={200} value={form[field.key]} onChange={event => {setWarnings([]); setForm({...form, [field.key]:event.target.value});}} /></label>)}</div>
            <label>Patient notes <span className="optional">(optional)</span><textarea maxLength={12000} rows={3} value={form.patient_records} onChange={event => {setWarnings([]);setForm({...form,patient_records:event.target.value});}} /></label>
            <details><summary>Additional history</summary>{(['medication_history','additional_diagnoses'] as const).map(key => <label key={key}>{key === 'medication_history' ? 'Medication history' : 'Additional diagnoses'}<textarea maxLength={12000} value={form[key]} onChange={event => {setWarnings([]);setForm({...form,[key]:event.target.value});}} /></label>)}</details>
            {warnings.length > 0 && <div className="warning" role="alert"><strong>Check before continuing</strong><ul>{warnings.map(item => <li key={item}>{item}</li>)}</ul><p>Submit again to confirm these details.</p></div>}
            <button disabled={busy || !csrf} type="submit">{busy ? 'Submitting…' : warnings.length ? 'Confirm and generate draft' : 'Generate draft →'}</button>
          </form>
        </section>
        <section aria-labelledby="orders-title"><h2 id="orders-title">Orders</h2>
          {!orders.length && <p className="muted">Your submitted orders and their generation status will appear here.</p>}
          <div className="order-list">{orders.map(order => <button key={order.id} className={'order ' + (order.id === selected ? 'selected' : '')} onClick={() => setSelected(order.id)} aria-pressed={order.id === selected}><span><strong>{order.patient}</strong><small>{order.medication} · {order.mrn}</small></span><span className="status">{order.status}</span></button>)}</div>
          {active && <div className="draft"><div className="section-head"><h3>Draft preview</h3><span className="status" role="status">{active.status}</span></div>
            {active.status === 'completed' ? <><pre>{active.plan}</pre><a className="button" href={'/api/orders/'+active.id+'/download'}>Download draft ↓</a></> : <p>{active.status === 'failed' ? 'Generation stopped after three attempts.' : 'The worker will process this order. You can keep working while it runs.'}</p>}
            {active.error && <p className="error">{active.error}</p>}
            {active.status === 'failed' && <button disabled={busy} onClick={() => retry(active)}>Retry generation</button>}
          </div>}
        </section>
      </div>
    </main><footer>Portfolio prototype · Drafts require pharmacist review</footer>
  </div>;
}
createRoot(document.getElementById('root')!).render(<App />);
