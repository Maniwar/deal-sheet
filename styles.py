"""The app's look: one stylesheet, built on the tokens at the top."""

CSS = """
:root{
  --bg:#0b0c0e; --card:#16181c; --card2:#111317; --line:#262930; --line2:#383c45;
  --ink:#f5f6f8; --mute:#a6abb5; --dim:#737985;
  --green:#34d399; --green-ink:#06281c; --amber:#f5b84a; --red:#ef4444; --indigo:#a5b4fc;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'DM Sans',system-ui,-apple-system,'Segoe UI',sans-serif;
}
/* layout idea: one deal "ticket" on top that always shows the state of play, steps below it */
.stApp{background:#0b0c0e}
/* the main screen is one full-height stage, edge to edge; Streamlit's own bar is tucked away
   (the stage's settings button opens the sidebar) */
header[data-testid="stHeader"]{background:transparent;height:0;min-height:0;overflow:hidden;visibility:hidden}
[data-testid="stMainBlockContainer"]{max-width:none!important;padding:0 0 4rem!important}
[data-testid="stMainBlockContainer"]>[data-testid="stVerticalBlock"]{gap:0}
.st-key-stagebox{margin:0}
.st-key-details{max-width:1080px;margin:0 auto;padding:34px 18px 0;scroll-margin-top:8px}
.st-key-details h2{font:700 26px var(--sans);letter-spacing:-.02em;color:var(--ink);padding-bottom:.2rem}
/* nothing on the page fades while the app works: the stage shows its own progress */
[data-testid="stElementContainer"][data-stale="true"],[data-stale="true"]{opacity:1!important;transition:none!important}
[data-testid="stStatusWidget"]{display:none}
[data-testid="stSidebar"]{background:#0e0f12;border-right:1px solid var(--line)}
[data-testid="stSidebar"] h3{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);font-family:var(--mono);font-weight:700;margin-top:.6rem}
.stAppDeployButton,[data-testid="stDecoration"]{display:none}

/* ---------- hero ticket ---------- */
.ds-hero{position:relative;border:1px solid var(--line);border-radius:22px;padding:26px 28px 22px;
  background:linear-gradient(180deg,rgba(22,24,28,.96),rgba(17,19,23,.96));
  box-shadow:0 30px 80px -40px rgba(16,185,129,.35),0 1px 0 rgba(255,255,255,.04) inset;overflow:hidden}
.ds-hero::before{content:"";position:absolute;left:0;top:0;height:3px;width:100%;
  background:linear-gradient(90deg,var(--green) 0,var(--green) 22%,#262930 22%)}
.ds-top{display:flex;gap:24px;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.ds-eyebrow{font:700 11px var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--dim);display:flex;gap:10px;align-items:center}
.ds-tag{font:700 10px var(--mono);letter-spacing:.1em;color:var(--amber);border:1px solid rgba(245,158,11,.45);background:rgba(245,158,11,.08);padding:3px 8px;border-radius:999px}
.ds-tag.ok{color:#6ee7b7;border-color:rgba(16,185,129,.5);background:rgba(16,185,129,.10)}
.ds-title{font:700 clamp(28px,4.6vw,44px)/1.05 var(--sans);letter-spacing:-.02em;color:var(--ink);margin:10px 0 12px;text-wrap:balance}
.ds-chips{display:flex;flex-wrap:wrap;gap:6px}
.ds-chips span{font:500 12.5px var(--sans);color:#d5d9e0;background:#1b1d22;border:1px solid var(--line);padding:5px 10px;border-radius:999px}
.ds-seller{margin-top:10px;color:var(--mute);font:500 13.5px var(--sans)}
.ds-ask{text-align:right;min-width:190px}
.ds-label{font:700 10.5px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--dim)}
.ds-asknum{font:700 clamp(30px,4.4vw,42px)/1.1 var(--mono);color:var(--ink);font-variant-numeric:tabular-nums;margin-top:6px}
.ds-gap{display:inline-block;margin-top:8px;font:500 12.5px var(--sans);padding:4px 10px;border-radius:999px}
.ds-gap.up{color:#fcd34d;background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.35)}
.ds-gap.down{color:#6ee7b7;background:rgba(16,185,129,.10);border:1px solid rgba(16,185,129,.35)}
.ds-gap.flat{color:var(--mute);background:#1b1d22;border:1px solid var(--line)}

/* ---------- price rail ---------- */
.ds-railwrap{margin-top:22px;padding:14px 18px 10px;border:1px solid var(--line);border-radius:16px;background:rgba(2,6,23,.55)}
.ds-railhead{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center}
.ds-legend{display:flex;gap:14px;flex-wrap:wrap;font:500 12px var(--sans);color:var(--mute)}
.ds-legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.ds-legend i.sold{background:var(--green)} .ds-legend i.high_bid{background:var(--amber)}
.ds-legend i.asking{box-sizing:border-box;border:2px solid var(--mute);background:transparent}
.ds-legend i.band{border-radius:4px;width:18px;background:rgba(16,185,129,.22);border:1px solid rgba(16,185,129,.55)}
.ds-rail{position:relative;height:104px;margin:6px 10px 0}
.ds-rail .track{position:absolute;left:0;right:0;top:60px;height:4px;border-radius:4px;background:#262930}
.ds-rail .band{position:absolute;top:53px;height:18px;border-radius:9px;background:rgba(16,185,129,.16);border:1px solid rgba(16,185,129,.5)}
.ds-rail .target{position:absolute;top:48px;height:28px;width:2px;margin-left:-1px;background:var(--green);box-shadow:0 0 14px rgba(16,185,129,.9)}
.ds-rail .stem{position:absolute;top:26px;height:44px;width:2px;margin-left:-1px;background:#e2e8f0}
.ds-rail .flag{position:absolute;top:4px;font:700 10.5px var(--mono);letter-spacing:.06em;color:#0b0c0e;background:#e2e8f0;padding:4px 8px;border-radius:7px;white-space:nowrap}
.ds-rail .dot{position:absolute;width:14px;height:14px;border-radius:50%;margin:-7px 0 0 -7px;border:2px solid #0b0c0e;box-sizing:border-box}
.ds-rail .dot.sold{background:var(--green);box-shadow:0 0 0 1px rgba(16,185,129,.35),0 0 12px rgba(16,185,129,.45)}
.ds-rail .dot.high_bid{background:var(--amber)}
.ds-rail .dot.asking{background:#111317;border:2px solid #94a3b8}
.ds-rail .tick{position:absolute;top:80px;transform:translateX(-50%);font:500 11px var(--mono);color:var(--dim)}
.ds-rail .tick::before{content:"";position:absolute;left:50%;top:-12px;width:1px;height:7px;background:#263349}
.ds-empty{color:var(--dim);font:500 13.5px var(--sans);padding:18px 4px 12px}

/* ---------- ladder tiles ---------- */
.ds-ladder{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:14px}
.ds-tile{border:1px solid var(--line);border-radius:14px;padding:12px 14px;background:rgba(2,6,23,.45);min-width:0}
.ds-tile .v{font:700 clamp(17px,2.4vw,22px)/1.2 var(--mono);margin-top:6px;font-variant-numeric:tabular-nums;white-space:nowrap}
.ds-tile .s{font:500 12px var(--sans);color:var(--mute);margin-top:3px}
.ds-tile.open .v{color:var(--indigo)} .ds-tile.target .v{color:var(--green)} .ds-tile.walk .v{color:var(--ink)} .ds-tile.otd .v{color:#fcd34d}
.ds-tile.target{border-color:rgba(16,185,129,.45);background:rgba(16,185,129,.06)}
.ds-tile .v.unset{color:var(--dim);font-size:15px;font-family:var(--sans);font-weight:500}

/* ---------- comp cards ---------- */
.ds-comps{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px;margin:6px 0 14px}
.ds-comp{display:block;text-decoration:none!important;border:1px solid var(--line);border-left:3px solid var(--mute);border-radius:14px;padding:12px 14px;background:var(--card);transition:border-color .15s,transform .15s}
a.ds-comp:hover{border-color:var(--line2);transform:translateY(-1px)}
.ds-comp.sold{border-left-color:var(--green)} .ds-comp.high_bid{border-left-color:var(--amber)} .ds-comp.asking{border-left-color:#64748b}
.ds-comp.off{opacity:.45}
.ds-comp .r1{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.ds-pill{font:700 9.5px var(--mono);letter-spacing:.1em;padding:3px 8px;border-radius:999px;color:#0b0c0e}
.ds-pill.sold{background:var(--green)} .ds-pill.high_bid{background:var(--amber)} .ds-pill.asking{background:#94a3b8}
.ds-comp .p{font:700 19px var(--mono);color:var(--ink);font-variant-numeric:tabular-nums}
.ds-comp .d{font:500 11.5px var(--sans);color:var(--mute);margin-left:auto}
.ds-comp .t{font:500 14px var(--sans);color:var(--ink);margin-top:7px}
.ds-comp .m{font:400 12.5px var(--sans);color:var(--mute);margin-top:2px}
.ds-comp .n{font:400 12.5px var(--sans);color:var(--dim);margin-top:5px}
.ds-comp .u{font:500 10.5px/1.45 var(--mono);color:#7dd3fc;margin-top:6px;overflow-wrap:anywhere}
.ds-comp .k{font:500 11.5px var(--sans);margin-top:7px}
.ds-comp .k.ok{color:#6ee7b7} .ds-comp .k.warn{color:#fcd34d} .ds-comp .k.none{color:var(--dim)}

/* ---------- misc blocks ---------- */
.ds-h{font:700 11px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin:8px 0 2px}
.ds-note{border:1px solid var(--line);border-radius:14px;padding:12px 14px;background:var(--card2);color:#d5d9e0;font:400 14px/1.5 var(--sans)}
.ds-note b{color:var(--ink)}
.ds-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:4px 0 12px}
.ds-math{width:100%;border-collapse:collapse;font:500 14px var(--sans)}
.ds-math td{padding:7px 0;border-bottom:1px solid var(--line);color:#d5d9e0}
.ds-math td:last-child{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink)}
.ds-math tr.total td{border-bottom:0;color:var(--ink);font-weight:700}
.ds-math tr.total td:last-child{color:#fcd34d;font-size:17px}

/* ---------- Streamlit widgets ---------- */
[data-testid="stTabs"] [role="tablist"]{display:flex;gap:6px;background:var(--card2);border:1px solid var(--line);padding:6px;border-radius:16px;margin-top:6px}
[data-testid="stTabs"] [data-orientation="horizontal"]{border-bottom:0!important;box-shadow:none!important}
[data-testid="stTabs"] [data-orientation="horizontal"]::after,[data-testid="stTabs"] [data-orientation="horizontal"]::before{display:none!important}
[data-testid="stTab"]{flex:1;display:flex;align-items:center;justify-content:center;height:42px;border-radius:11px;padding:0 18px;margin:0;color:var(--mute);transition:background .15s}
[data-testid="stTab"] p{font-weight:700;font-size:14.5px;color:var(--mute)}
[data-testid="stTab"]:hover{background:#1b1d22}
[data-testid="stTab"]:hover p{color:var(--ink)}
[data-testid="stTab"][aria-selected="true"]{background:var(--green);box-shadow:0 10px 26px -14px rgba(16,185,129,.95)}
[data-testid="stTab"][aria-selected="true"] p{color:var(--green-ink)}
[data-testid="stTab"] .react-aria-SelectionIndicator{display:none!important}
[data-testid="stTabPanel"]{padding-top:18px}
button[kind="primary"]:not(:disabled){color:var(--green-ink)!important;font-weight:700!important;box-shadow:0 10px 30px -14px rgba(16,185,129,.9)}
button[kind="primary"]:not(:disabled) p{color:var(--green-ink)!important;font-weight:700}
button[kind="primary"]:disabled{background:#16181c!important;border:1px dashed var(--line2)!important;color:var(--dim)!important}
button[kind="primary"]:disabled p{color:var(--dim)!important;font-weight:600}
button[kind="secondary"]{background:#111317;border-color:var(--line2)}
[data-testid="stExpander"] details{border-color:var(--line);background:var(--card2);border-radius:14px}
[data-testid="stFileUploaderDropzone"]{background:var(--card2);border:1px dashed var(--line2)}
[data-testid="stImage"] img{border-radius:12px;border:1px solid var(--line);box-shadow:0 30px 70px -40px rgba(0,0,0,.9)}
h4{letter-spacing:-.01em}
:focus-visible{outline:2px solid var(--green);outline-offset:2px}

@media (max-width:640px){
  [data-testid="stMainBlockContainer"]{padding-left:1rem;padding-right:1rem;padding-top:3.2rem}
  .ds-hero{padding:20px 14px 14px;border-radius:18px}
  .ds-title{font-size:29px;margin:8px 0 10px}
  .ds-asknum{font-size:30px}
  .ds-top{gap:14px}
  .ds-tile{padding:10px 12px}
  .ds-railwrap{margin-top:16px}
  .ds-ask{text-align:left;min-width:0}
  .ds-ladder{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ds-railwrap{padding:12px 10px 8px}
  .ds-rail .tick{font-size:10px}
  [data-testid="stTab"]{padding:0 6px}
  [data-testid="stTab"] p{font-size:13.5px}
}
@media (prefers-reduced-motion:reduce){.ds-comp{transition:none}}
"""
