/**
 * Rood Cab connect-server (Node) — mints Zapier connect-links.
 *
 * Why Node: the Zapier SDK (@zapier/zapier-sdk) is Node-only, so this is a SEPARATE
 * service that sits beside the Python agent. The static site calls POST /connect-link;
 * the provider authorizes DisputeFox in a Zapier-hosted window; Zapier redirects back
 * to GET /connected, where we attach the connection to the provider in the Python API.
 *
 * Status: SCAFFOLD. The two SDK calls below are marked TODO and currently return a
 * clearly-labelled placeholder so the end-to-end flow is visible. Wire the real calls
 * against https://docs.zapier.com/sdk before production.
 *
 * Setup:
 *   cd connect-server && npm install && npx zapier-sdk login   (use --non-interactive in CI)
 *   ROODCAB_API=http://localhost:8000 PUBLIC_BASE=http://localhost:8787 npm start
 */
import http from "node:http";
// import { Zapier } from "@zapier/zapier-sdk";   // TODO(real-sdk): confirm import per docs.

const PORT = process.env.PORT || 8787;
const PUBLIC_BASE = process.env.PUBLIC_BASE || `http://localhost:${PORT}`;
const ROODCAB_API = process.env.ROODCAB_API || "http://localhost:8000";

// const zapier = new Zapier();  // credentials come from `zapier-sdk login`

function send(res, code, obj) {
  res.writeHead(code, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  });
  res.end(JSON.stringify(obj));
}

async function readJson(req) {
  let body = "";
  for await (const chunk of req) body += chunk;
  try { return JSON.parse(body || "{}"); } catch { return null; }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, PUBLIC_BASE);

  if (req.method === "OPTIONS") { res.writeHead(204, { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type" }); return res.end(); }

  // 1) Mint a connect link for a provider to authorize DisputeFox.
  if (req.method === "POST" && url.pathname === "/connect-link") {
    const data = await readJson(req);
    if (!data) return send(res, 400, { error: "bad json" });
    try {
      // TODO(real-sdk): create the hosted connect link. Per docs.zapier.com/sdk the
      // connect flow returns a URL the user completes, then redirects to redirectUri.
      //
      //   const { url: connect_url } = await zapier.connections.createConnectLink({
      //     app: data.app || "disputefox",
      //     redirectUri: `${PUBLIC_BASE}/connected?provider=${data.provider_id}&token=${data.api_token}`,
      //   });
      //
      // Placeholder until wired:
      const connect_url =
        `https://connect.zapier.com/placeholder?provider=${encodeURIComponent(data.provider_id || "")}` +
        `&app=${encodeURIComponent(data.app || "disputefox")}`;
      return send(res, 200, { connect_url, placeholder: true });
    } catch (e) {
      return send(res, 500, { error: String(e) });
    }
  }

  // 2) Zapier redirects here after the provider authorizes. Attach the connection to
  //    the provider in the Python API, then tell them to return to Rood Cab.
  if (req.method === "GET" && url.pathname === "/connected") {
    const provider = url.searchParams.get("provider");
    const token = url.searchParams.get("token");
    try {
      // TODO(real-sdk): read the established connection id from the SDK callback.
      const connection_id = url.searchParams.get("connection_id") || "conn_placeholder";
      await fetch(`${ROODCAB_API}/v1/providers/${provider}/zapier`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ connection_id }),
      });
    } catch (e) { /* log + show a friendly error in production */ }
    res.writeHead(200, { "Content-Type": "text/html" });
    return res.end("<p>Connected. You can close this window and return to Rood Cab.</p>");
  }

  send(res, 404, { error: "not found" });
});

server.listen(PORT, () => console.log(`Rood Cab connect-server on :${PORT} -> API ${ROODCAB_API}`));
