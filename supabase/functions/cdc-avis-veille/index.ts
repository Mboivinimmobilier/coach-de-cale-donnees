// Coach de câle — avis de la veille (« demain matin s'annonce bon »), par animal (orignal ou chevreuil)
// Appelée chaque soir par pg_cron. Calcule la météo de l'aube du lendemain pour chaque région abonnée
// et envoie une notification seulement si le matin s'annonce bon pour l'animal choisi par l'abonné.
// Orignal : rapport « Orignal météo et comportement ». Chevreuil : rapport « Chevreuil et carte écoforestière » et guide DOC_CERF.
import webpush from "npm:web-push@3.6.7";
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "content-type, apikey, authorization, x-cdc-cron", "Access-Control-Allow-Methods": "GET, POST, OPTIONS" };
const json = (o: unknown, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { ...CORS, "Content-Type": "application/json" } });

async function cfg(k: string): Promise<string | null> {
  const { data } = await sb.from("cdc_cfg").select("v").eq("k", k).maybeSingle();
  return data?.v ?? null;
}
async function vapid() {
  let pub = await cfg("vapid_public"), priv = await cfg("vapid_private");
  if (!pub || !priv) {
    const k = webpush.generateVAPIDKeys();
    await sb.from("cdc_cfg").upsert([{ k: "vapid_private", v: k.privateKey }], { onConflict: "k", ignoreDuplicates: true });
    await sb.from("cdc_cfg").upsert([{ k: "vapid_public", v: k.publicKey }], { onConflict: "k", ignoreDuplicates: true });
    pub = await cfg("vapid_public"); priv = await cfg("vapid_private");
  }
  webpush.setVapidDetails("mailto:avis@coach-de-cale.netlify.app", pub!, priv!);
  return pub!;
}

type Esp = "orignal" | "cerf";
const espOk = (e: unknown): Esp => (e === "cerf" ? "cerf" : "orignal");

// ---- Règles de l'orignal (mêmes valeurs que l'app) ----
const RUT: [number, number, string, number][] = [[901, 917, "Pré-rut", .4], [918, 919, "Début du rut", .7], [920, 1005, "Plein rut", 1], [1006, 1011, "Fin du rut", .7], [1012, 1020, "Post-rut", .5], [1021, 1130, "Fin de saison", .4]];
// ---- Chevreuil : calendrier déduit pour le Québec (pic vers le 12-25 novembre) ----
const RUT_C: [number, number, string, number][] = [[1001, 1019, "Avant le rut", .45], [1020, 1107, "Pré-rut", .7], [1108, 1124, "Plein rut", 1], [1125, 1210, "Post-rut", .6], [1211, 1225, "Second rut", .5]];
const rutOf = (ymd: string, esp: Esp) => { const md = Number(ymd.slice(5, 7)) * 100 + Number(ymd.slice(8, 10)); const r = (esp === "cerf" ? RUT_C : RUT).find(x => md >= x[0] && md <= x[1]); return r ? { lbl: r[2], base: r[3] } : null; };
const TM: [number, number][] = [[0, 1.1], [5, 1], [10, .85], [15, .7], [20, .5], [25, .35], [30, .25]];
const tMult = (t: number) => { if (t <= 0) return 1.1; for (let i = 1; i < TM.length; i++) { const [a, va] = TM[i - 1], [b, vb] = TM[i]; if (t <= b) return va + (vb - va) * (t - a) / (b - a); } return .25; };
// Chevreuil : pas de stress de chaleur comme l'orignal ; le frais aide un peu, le très chaud et le très froid nuisent un peu
const tMultC = (t: number) => t <= -20 ? .8 : t <= -10 ? .95 : t <= 8 ? 1.05 : t <= 15 ? 1 : .85;
const hm = (s: string) => Number(s.slice(11, 13)) * 60 + Number(s.slice(14, 16));
const deg = (x: number) => `${Math.round(x)}°`;

type Matin = { ok: boolean; title: string; body: string; v: number; day: string; esp: Esp } | null;
async function matinDemain(lat: number, lon: number, esp: Esp = "orignal"): Promise<Matin> {
  const u = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation,snow_depth&daily=sunrise,sunset,temperature_2m_max&forecast_days=3&timezone=auto`;
  const r = await fetch(u); if (!r.ok) return null;
  const j = await r.json(), H = j.hourly, D = j.daily;
  const day = D.time[1] as string; // demain (date locale)
  const rut = rutOf(day, esp); if (!rut) return null; // hors saison : pas d'avis
  const sr = hm(D.sunrise[1]), endDawn = Math.max(sr + 120, (esp === "cerf" ? 10 * 60 + 30 : 9 * 60 + 30)), start = sr - 30;
  const idx: number[] = [];
  (H.time as string[]).forEach((t, i) => { if (t.slice(0, 10) === day) { const m = hm(t) + 30; if (m >= start && m <= endDawn) idx.push(i); } });
  if (!idx.length) return null;
  const T = idx.map(i => H.temperature_2m[i]), W = idx.map(i => H.wind_speed_10m[i]), G = idx.map(i => H.wind_gusts_10m[i] ?? H.wind_speed_10m[i]);
  const rain = idx.reduce((a, i) => a + (H.precipitation[i] || 0), 0), snow = Math.max(...idx.map(i => H.snow_depth?.[i] ?? 0));
  const tMin = Math.min(...T), tAvg = T.reduce((a, b) => a + b, 0) / T.length, wAvg = W.reduce((a, b) => a + b, 0) / W.length, gMax = Math.max(...G);
  const hSr = `${Math.floor(sr / 60)} h ${String(sr % 60).padStart(2, "0")}`;
  const ventTxt = `vent ${Math.round(wAvg)} km/h`;
  let title = "", body = "", ok = false, v = 0;
  if (esp === "cerf") {
    // Front froid : l'aube de demain au moins 6° plus froide que l'aube d'aujourd'hui
    const d0 = D.time[0] as string, sr0 = hm(D.sunrise[0]);
    const T0 = (H.time as string[]).map((t, i) => [t, i] as [string, number]).filter(([t]) => t.slice(0, 10) === d0 && hm(t) + 30 >= sr0 - 30 && hm(t) + 30 <= Math.max(sr0 + 120, 10 * 60 + 30)).map(([, i]) => H.temperature_2m[i]);
    const front = T0.length > 0 && T0.reduce((a: number, b: number) => a + b, 0) / T0.length - tAvg >= 6;
    let m = tMultC(tAvg); if (wAvg >= 30) m *= .6; else if (wAvg >= 24) m *= .8; else if (wAvg < 3) m *= .95;
    if (rain >= 3) m *= .8; if (snow >= .4) m *= .85;
    v = Math.round(Math.min(100, 100 * rut.base * m));
    const ratel = rut.base >= .7 && wAvg < 20 && rain < 1;
    if (front && wAvg < 24 && rain < 1 && v >= 55) {
      ok = true; title = "🦌 Demain matin : coup de froid";
      body = `${deg(tMin)} à l'aube, au moins 6° de moins que ce matin, ${ventTxt}. Les chevreuils bougent souvent plus après un front froid. Sois au mirador avant ${hSr}. ${rut.lbl} · indice ${v}.`;
    } else if (v >= 70 && wAvg < 20 && gMax < 40 && rain < 1) {
      ok = true; title = "🦌 Demain matin : bon pour le chevreuil";
      body = `${deg(tMin)} à l'aube, ${ventTxt}. ${ratel ? "Bon matin pour râteler entre 7 h 30 et 10 h 30 : surveille le côté sous le vent." : "Affût sur un passage entre la couche et la nourriture, le vent dans la face."} Lever du soleil ${hSr}. ${rut.lbl} · indice ${v}.`;
    } else if (snow >= .02 && snow < .2 && rain < 1 && v >= 45) {
      ok = true; title = "❄️ Demain : neige au sol";
      body = `Pistes fraîches faciles à lire pour la chasse fine. ${deg(tMin)}, ${ventTxt}. ${rut.lbl} · indice ${v}.`;
    }
    return { ok, title, body, v, day, esp };
  }
  const teff = tAvg - (wAvg >= 18 ? 3 : wAvg >= 10 ? 1.5 : 0), tm = tMult(teff), tempM = tm > 1 ? tm : 1 - (1 - tm) * .35;
  let m = 1; if (snow >= .3) m *= .75;
  v = Math.round(Math.min(100, 100 * rut.base * tempM * m));
  if (tMin <= 0 && wAvg < 5 && rain < 1) {
    ok = true; title = "🥶 Demain matin idéal : gel et calme";
    body = `${deg(tMin)}, ${ventTxt}. Ton câl va porter très loin. Sois au poste avant ${hSr} et câle jusqu'à 9 h 30. ${rut.lbl} · indice ${v}.`;
  } else if (v >= 60 && wAvg < 15 && gMax < 40 && rain < 1) {
    ok = true; title = "🫎 Demain matin : bon pour câler";
    body = `${deg(tMin)} à l'aube, ${ventTxt}. ${wAvg < 5 ? "Calme : ton câl va porter loin." : "Place le tireur sous le vent du câleur."} Lever du soleil ${hSr}. ${rut.lbl} · indice ${v}.`;
  } else if (snow >= .02 && snow < .3 && rain < 1 && v >= 45) {
    ok = true; title = "❄️ Demain : neige au sol";
    body = `Pistes fraîches faciles à lire. ${deg(tMin)}, ${ventTxt}. ${rut.lbl} · indice ${v}.`;
  }
  return { ok, title, body, v, day, esp };
}

async function send(row: { endpoint: string; p256dh: string; auth: string }, payload: unknown) {
  try {
    await webpush.sendNotification({ endpoint: row.endpoint, keys: { p256dh: row.p256dh, auth: row.auth } }, JSON.stringify(payload), { TTL: 6 * 3600, urgency: "normal" });
    return true;
  } catch (e) {
    const code = (e as { statusCode?: number }).statusCode;
    if (code === 404 || code === 410) await sb.from("cdc_push").delete().eq("endpoint", row.endpoint); // abonnement expiré
    return false;
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  const url = new URL(req.url);
  try {
    const pub = await vapid();
    if (url.searchParams.get("cle")) return json({ pub });
    // Aperçu du calcul pour une position (aucun envoi) : ?apercu=lat,lon[&esp=cerf]
    const ap = url.searchParams.get("apercu");
    if (ap) { const [la, lo] = ap.split(",").map(Number); return json(await matinDemain(la, lo, espOk(url.searchParams.get("esp")))); }
    if (url.searchParams.get("test")) {
      const b = await req.json().catch(() => ({}));
      const { data } = await sb.from("cdc_push").select("endpoint,p256dh,auth,lat,lon,esp").eq("endpoint", b.endpoint || "").maybeSingle();
      if (!data) return json({ ok: false, err: "abonnement introuvable" }, 404);
      const M = await matinDemain(data.lat, data.lon, espOk(data.esp)).catch(() => null);
      const ok = await send(data, { title: "🔔 Avis activés", body: M ? (M.ok ? `Exemple pour demain : ${M.title.replace(/^\S+\s/, "")}.` : `Demain matin s'annonce moyen (indice ${M.v}) : pas d'avis ce soir. Tu en recevras un la veille des bons matins.`) : "Tu recevras un avis la veille des bons matins de chasse.", url: M ? `/?ouvrir=meteo&date=${M.day}` : "/?ouvrir=meteo" });
      return json({ ok });
    }
    const tok = await cfg("cron_token");
    if (!tok || req.headers.get("x-cdc-cron") !== tok) return json({ err: "non autorisé" }, 401);
    const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/Toronto" });
    const { data: rows } = await sb.from("cdc_push").select("endpoint,p256dh,auth,lat,lon,last_sent,esp");
    const groups = new Map<string, typeof rows>();
    (rows || []).forEach(r => { if (r.last_sent === today || r.lat == null) return; const k = `${Math.round(r.lat * 10) / 10},${Math.round(r.lon * 10) / 10},${espOk(r.esp)}`; if (!groups.has(k)) groups.set(k, []); groups.get(k)!.push(r); });
    let sent = 0, skip = 0;
    for (const [k, list] of groups) {
      const [la, lo, e] = k.split(",");
      const M = await matinDemain(Number(la), Number(lo), espOk(e)).catch(() => null);
      if (!M || !M.ok) { skip += list!.length; continue; }
      for (const r of list!) { if (await send(r, { title: M.title, body: M.body, url: `/?ouvrir=meteo&date=${M.day}` })) { sent++; await sb.from("cdc_push").update({ last_sent: today }).eq("endpoint", r.endpoint); } }
    }
    return json({ ok: true, groups: groups.size, sent, skip });
  } catch (e) {
    return json({ err: String(e) }, 500);
  }
});
