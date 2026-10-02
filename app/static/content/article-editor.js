/*
 * Filesystem articles editor — an ES module so it runs both
 *
 *   - inside django-admin-react, as a CUSTOM_PAGES entry (the SPA imports
 *     this file and calls mount(element, context)), and
 *   - standalone, from templates/content/editor.html (older SPA builds).
 *
 * It only talks to /api/content/ with the session cookie + X-CSRFToken.
 * All markup and styles are scoped under .fse so nothing leaks into the
 * host page.
 */

const CSS = `
.fse { --border:#e5e7eb; --muted:#6b7280; --text:#111827; --bg:#f9fafb; --accent:#047857; --accent-bg:#ecfdf5; --danger:#b91c1c; }
.fse, .fse * { box-sizing: border-box; }
.fse { margin:0; font:14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; color:var(--text); background:var(--bg); }
.fse .fse-header { display:flex; align-items:center; gap:1rem; padding:.75rem 1.25rem; background:#fff; border-bottom:1px solid var(--border); }
.fse .fse-header h1 { font-size:1rem; margin:0; }
.fse .fse-header a { color:var(--muted); text-decoration:none; }
.fse .badge { display:inline-flex; align-items:center; gap:.35rem; padding:.15rem .55rem; border-radius:999px; font-size:12px; font-weight:600; background:var(--accent-bg); color:var(--accent); border:1px solid #a7f3d0; }
.fse .badge.draft { background:#fffbeb; color:#92400e; border-color:#fde68a; }
.fse .fse-main { display:grid; grid-template-columns: minmax(18rem, 26rem) 1fr; gap:1rem; padding:1rem 1.25rem; }
@media (max-width: 800px) { .fse .fse-main { grid-template-columns: 1fr; } }
.fse .card { background:#fff; border:1px solid var(--border); border-radius:.5rem; }
.fse .card h2 { font-size:.9rem; margin:0; padding:.75rem 1rem; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }
.fse .filters { display:flex; flex-wrap:wrap; gap:.5rem; padding:.75rem 1rem; border-bottom:1px solid var(--border); }
.fse select, .fse input, .fse textarea { font:inherit; font-weight:400; padding:.4rem .5rem; border:1px solid #d1d5db; border-radius:.375rem; background:#fff; width:100%; }
.fse .filters select { width:auto; }
.fse ul.list { list-style:none; margin:0; padding:0; max-height:70vh; overflow:auto; }
.fse ul.list li { padding:.6rem 1rem; border-bottom:1px solid var(--border); cursor:pointer; }
.fse ul.list li:hover, .fse ul.list li.active { background:#f3f4f6; }
.fse ul.list .meta { color:var(--muted); font-size:12px; }
.fse form { padding:1rem; display:grid; gap:.75rem; }
.fse .row { display:grid; grid-template-columns: repeat(3, 1fr); gap:.75rem; }
.fse label { display:grid; gap:.25rem; font-weight:600; font-size:12px; color:#374151; }
.fse textarea { min-height:22rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px; }
.fse .errors { color:var(--danger); font-weight:400; font-size:12px; }
.fse .actions { display:flex; gap:.5rem; align-items:center; }
.fse button { font:inherit; font-weight:600; padding:.45rem .9rem; border-radius:.375rem; border:1px solid #d1d5db; background:#fff; cursor:pointer; }
.fse button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
.fse button.danger { color:var(--danger); border-color:#fecaca; margin-left:auto; }
.fse .location { font-family: ui-monospace, monospace; font-size:12px; color:var(--muted); padding:.5rem 1rem; border-bottom:1px solid var(--border); background:#f9fafb; }
.fse #notice { padding:.5rem 1rem; display:none; }
.fse #notice.ok { display:block; background:var(--accent-bg); color:var(--accent); }
.fse #notice.err { display:block; background:#fef2f2; color:var(--danger); }
.fse .empty { padding:2rem; color:var(--muted); text-align:center; }
.fse .badge.git { background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe; }
.fse .badge.warn { background:#fffbeb; color:#92400e; border-color:#fde68a; }
.fse #history { border-top:1px solid var(--border); }
.fse #history h3 { font-size:.85rem; margin:0; padding:.75rem 1rem; }
.fse #history table { width:100%; border-collapse:collapse; font-size:12px; }
.fse #history td { padding:.4rem 1rem; border-top:1px solid var(--border); vertical-align:top; }
.fse #history code { font-size:12px; }
.fse #history button { padding:.2rem .5rem; font-size:12px; }
.fse pre#diff { margin:0; padding:.75rem 1rem; max-height:20rem; overflow:auto; background:#0b1020; color:#e5e7eb; font-size:12px; }
.fse pre#diff .add { color:#86efac; } pre#diff .del { color:#fca5a5; }
.fse.fse--embedded { background:transparent; }
.fse.fse--embedded .fse-header { background:transparent; border-bottom:0; padding:0 0 .75rem; flex-wrap:wrap; }
.fse.fse--embedded .fse-main { padding:0; }
.fse.fse--embedded .fse-back { display:none; }
.fse--dark { --border:#374151; --muted:#9ca3af; --text:#f3f4f6; --bg:#111827; --accent-bg:#064e3b; }
.fse--dark .card, .fse--dark select, .fse--dark input, .fse--dark textarea, .fse--dark button { background:#1f2937; color:var(--text); border-color:#4b5563; }
.fse--dark ul.list li:hover, .fse--dark ul.list li.active, .fse--dark .location { background:#111827; }
.fse--dark label { color:#d1d5db; }
.fse--dark button.primary { background:var(--accent); }
`;

const MARKUP = `
<header class="fse-header">
  <a class="fse-back" href="/admin-react/">← React Admin</a>
  <h1>Articles</h1>
  <span class="badge" id="backend" title="Stored as Markdown files, not in the database">📁 Filesystem repository</span>
  <span id="repo-state" class="badge" hidden></span>
  <button type="button" id="sync" hidden title="Fetch, fast-forward and push. Never merges.">Sync with remote</button>
  <span id="root" class="meta"></span>
</header>
<main class="fse-main">
  <section class="card">
    <h2><span>Documents <span id="count" class="meta"></span></span> <button type="button" id="new">+ New article</button></h2>
    <div class="filters">
      <select id="f-market"><option value="">All markets</option></select>
      <select id="f-locale"><option value="">All locales</option></select>
      <select id="f-category"><option value="">All categories</option></select>
      <select id="f-status"><option value="">Any status</option></select>
    </div>
    <ul class="list" id="list"></ul>
  </section>
  <section class="card" id="editor">
    <h2><span id="editor-title">Select an article</span> <span id="editor-status"></span></h2>
    <div class="location" id="location">No file selected.</div>
    <div id="notice"></div>
    <form id="form" hidden novalidate>
      <label>Title <input name="title" required><span class="errors" data-for="title"></span></label>
      <div class="row">
        <label>Market <select name="market"></select><span class="errors" data-for="market"></span></label>
        <label>Locale <select name="locale"></select><span class="errors" data-for="locale"></span></label>
        <label>Slug (file name) <input name="slug" pattern="[a-z0-9]+(-[a-z0-9]+)*"><span class="errors" data-for="slug"></span></label>
      </div>
      <div class="row">
        <label>Status <select name="status"></select><span class="errors" data-for="status"></span></label>
        <label>Category <select name="category"></select><span class="errors" data-for="category"></span></label>
        <label>Publication date (UTC) <input name="publication_date" type="datetime-local" step="1"><span class="errors" data-for="publication_date"></span></label>
      </div>
      <label>Body (Markdown) <textarea name="body"></textarea><span class="errors" data-for="body"></span></label>
      <span class="errors" data-for="document"></span>
      <div class="actions">
        <button class="primary" type="submit">Save to file</button>
        <a id="public" target="_blank" rel="noopener" hidden>View public page ↗</a>
        <button class="danger" type="button" id="delete">Delete file</button>
      </div>
    </form>
    <div id="history" hidden>
      <h3>History <span class="meta">(each save is a Git commit; restoring adds a new one)</span></h3>
      <table><tbody id="history-rows"></tbody></table>
      <pre id="diff" hidden></pre>
    </div>
  </section>
</main>
`;

let stylesInstalled = false;

function installStyles() {
	if (stylesInstalled || document.getElementById("fse-styles")) return;
	const style = document.createElement("style");
	style.id = "fse-styles";
	style.textContent = CSS;
	document.head.append(style);
	stylesInstalled = true;
}

export function mount(element, context = {}) {
	installStyles();
	const root = document.createElement("div");
	root.className = "fse";
	if (context.embedded) root.classList.add("fse--embedded");
	if (context.theme && context.theme() === "dark")
		root.classList.add("fse--dark");
	root.innerHTML = MARKUP; // static markup only; all data goes through textContent
	element.replaceChildren(root);

	const API = "/api/content/";
	const $ = (sel) => root.querySelector(sel);
	const form = $("#form");
	const F = form.elements; // F.title would be the title *attribute*
	let meta = null;
	let current = null; // article JSON being edited, null for a new one

	function csrfToken() {
		if (context.csrfToken) return context.csrfToken();
		const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
		return m ? decodeURIComponent(m[1]) : "";
	}

	async function call(method, url, body, headers = {}) {
		const res = await fetch(url, {
			method,
			credentials: "same-origin",
			headers: {
				"Content-Type": "application/json",
				"X-CSRFToken": csrfToken(),
				...headers,
			},
			body: body === undefined ? undefined : JSON.stringify(body),
		});
		let data = {};
		try {
			data = await res.json();
		} catch (_e) {
			/* non-JSON (e.g. CSRF page) */
		}
		if (!res.ok)
			throw Object.assign(new Error(data.error || res.statusText), {
				status: res.status,
				data,
			});
		return data;
	}

	function options(select, values, blank) {
		select.replaceChildren();
		if (blank) select.append(new Option(blank, ""));
		for (const v of values) select.append(new Option(v, v));
	}

	function notice(text, kind) {
		const el = $("#notice");
		el.textContent = text;
		el.className = kind || "";
	}

	function articleUrl(id) {
		return `${API}articles/${id}/`;
	}

	async function loadList() {
		const params = new URLSearchParams();
		for (const f of ["market", "locale", "category", "status"]) {
			const v = $(`#f-${f}`).value;
			if (v) params.set(f, v);
		}
		const data = await call("GET", `${API}articles/?${params}`);
		$("#count").textContent = `(${data.count})`;
		const list = $("#list");
		list.replaceChildren();
		if (!data.results.length) {
			const li = document.createElement("li");
			li.className = "empty";
			li.textContent = "No articles match.";
			list.append(li);
		}
		for (const a of data.results) {
			const li = document.createElement("li");
			li.dataset.id = a.id;
			if (current && current.id === a.id) li.className = "active";
			const title = document.createElement("div");
			title.textContent = a.title;
			const info = document.createElement("div");
			info.className = "meta";
			info.textContent = `${a.id} · ${a.category} · ${a.status} · ${a.publication_date.slice(0, 10)}`;
			li.append(title, info);
			li.addEventListener("click", () => open(a.id));
			list.append(li);
		}
	}

	function clearErrors() {
		form.querySelectorAll(".errors").forEach((e) => {
			e.textContent = "";
		});
	}

	function showErrors(errors) {
		for (const [field, messages] of Object.entries(errors || {})) {
			const el =
				form.querySelector(`.errors[data-for="${field}"]`) ||
				form.querySelector('.errors[data-for="document"]');
			el.textContent = messages.join(" ");
		}
	}

	function fillLocales(market, value) {
		options(F.locale, meta.markets[market] || []);
		if (value) F.locale.value = value;
	}

	function fill(article) {
		current = article;
		clearErrors();
		form.hidden = false;
		const a = article || {
			title: "",
			market: Object.keys(meta.markets)[0],
			slug: "",
			status: "draft",
			category: meta.categories[0],
			body: "",
			publication_date: new Date().toISOString(),
		};
		F.title.value = a.title;
		F.market.value = a.market;
		fillLocales(a.market, a.locale);
		F.slug.value = a.slug;
		F.status.value = a.status;
		F.category.value = a.category;
		F.publication_date.value = a.publication_date.slice(0, 19);
		F.body.value = a.body;
		$("#editor-title").textContent = article ? article.title : "New article";
		const status = $("#editor-status");
		status.textContent = article ? article.status : "";
		status.className = article
			? `badge ${article.status === "draft" ? "draft" : ""}`
			: "";
		$("#location").textContent = article
			? `📁 ${article.location}  ·  version ${article.version.slice(0, 12)}`
			: `📁 Will be written to ${meta.root}/<MARKET>/<locale>/articles/<slug>.md`;
		$("#delete").hidden = !article;
		const link = $("#public");
		link.hidden = !article?.public_url;
		if (article?.public_url) link.href = article.public_url;
		for (const li of root.querySelectorAll("#list li")) {
			li.classList.toggle("active", !!article && li.dataset.id === article.id);
		}
		loadHistory(article);
	}

	const versioned = () => meta?.capabilities.includes("history");

	async function loadHistory(article) {
		const box = $("#history");
		box.hidden = !(article && versioned());
		$("#diff").hidden = true;
		if (box.hidden) return;
		const rows = $("#history-rows");
		rows.replaceChildren();
		const data = await call("GET", `${articleUrl(article.id)}history/`);
		data.entries.forEach((entry, index) => {
			const tr = document.createElement("tr");
			const cells = [
				entry.short_version,
				entry.date.slice(0, 16).replace("T", " "),
				entry.author_name,
				entry.message,
			];
			cells.forEach((text, i) => {
				const td = document.createElement("td");
				if (i === 0) {
					const c = document.createElement("code");
					c.textContent = text;
					td.append(c);
				} else {
					td.textContent = text;
				}
				tr.append(td);
			});
			const actions = document.createElement("td");
			const show = document.createElement("button");
			show.type = "button";
			show.textContent = "Diff";
			show.addEventListener("click", () => showDiff(article, entry.version));
			actions.append(show);
			if (index > 0) {
				const restore = document.createElement("button");
				restore.type = "button";
				restore.textContent = "Restore";
				restore.addEventListener("click", () => restoreVersion(article, entry));
				actions.append(" ", restore);
			}
			tr.append(actions);
			rows.append(tr);
		});
	}

	async function showDiff(article, version) {
		const data = await call(
			"GET",
			`${articleUrl(article.id)}diff/?version=${encodeURIComponent(version)}`,
		);
		const pre = $("#diff");
		pre.replaceChildren();
		for (const line of data.diff.split("\n")) {
			const span = document.createElement("span");
			if (line.startsWith("+") && !line.startsWith("+++"))
				span.className = "add";
			if (line.startsWith("-") && !line.startsWith("---"))
				span.className = "del";
			span.textContent = `${line}\n`;
			pre.append(span);
		}
		pre.hidden = false;
	}

	async function restoreVersion(article, entry) {
		if (
			!confirm(
				`Restore ${article.id} to ${entry.short_version}? This creates a new commit.`,
			)
		)
			return;
		try {
			const saved = await call("POST", `${articleUrl(article.id)}restore/`, {
				version: entry.version,
				expected_version: article.version,
			});
			fill(saved);
			notice(
				savedMessage(saved, `Restored to ${entry.short_version}`),
				saved.commit?.push_error ? "err" : "ok",
			);
			await Promise.all([loadList(), loadStatus()]);
		} catch (e) {
			notice(e.message, "err");
		}
	}

	function savedMessage(saved, prefix) {
		let text = `${prefix || "Saved to"} ${saved.location}`;
		const c = saved.commit;
		if (c?.sha)
			text += ` · commit ${c.sha.slice(0, 10)}${c.pushed ? " · pushed" : ""}`;
		if (c && c.sha === null) text += " · no changes";
		if (c?.push_error) text += ` · NOT pushed: ${c.push_error}`;
		return text;
	}

	async function loadStatus() {
		if (!meta) return;
		const badge = $("#repo-state");
		try {
			const s = await call("GET", `${API}repository/`);
			const index = s.index ? ` · index ${s.index.state}` : "";
			badge.hidden = false;
			if (meta.source === "git") {
				badge.className = `badge ${s.ok ? "git" : "warn"}`;
				badge.textContent =
					(s.state
						? `${s.branch || "detached"} · ${s.state}${s.ahead ? ` · ${s.ahead} unpushed` : ""}`
						: "not a Git working tree") + index;
			} else {
				badge.className = "badge";
				badge.textContent = s.index
					? `index · ${s.index.rows} rows${s.index.invalid ? ` · ${s.index.invalid} invalid` : ""}`
					: "no index";
			}
			badge.title = (s.problems || []).join("\n");
		} catch (e) {
			badge.hidden = false;
			badge.className = "badge warn";
			badge.textContent = e.message;
		}
	}

	async function open(id) {
		notice("");
		try {
			fill(await call("GET", articleUrl(id)));
		} catch (e) {
			notice(e.message, "err");
		}
	}

	F.market.addEventListener("change", () => fillLocales(F.market.value));

	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		clearErrors();
		const payload = {
			title: F.title.value,
			market: F.market.value,
			locale: F.locale.value,
			slug: F.slug.value,
			status: F.status.value,
			category: F.category.value,
			publication_date: F.publication_date.value
				? `${F.publication_date.value}Z`
				: "",
			body: F.body.value,
		};
		try {
			let saved;
			if (current) {
				saved = await call("PUT", articleUrl(current.id), {
					...payload,
					version: current.version,
				});
			} else {
				saved = await call("POST", `${API}articles/`, payload);
			}
			fill(saved);
			notice(savedMessage(saved), saved.commit?.push_error ? "err" : "ok");
			await Promise.all([loadList(), loadStatus()]);
		} catch (e) {
			showErrors(e.data?.errors);
			notice(e.message, "err");
		}
	});

	$("#delete").addEventListener("click", async () => {
		if (!current || !confirm(`Delete ${current.location}?`)) return;
		try {
			const result = await call("DELETE", articleUrl(current.id), undefined, {
				"If-Match": current.version,
			});
			notice(
				`Deleted ${current.location}${result.commit?.sha ? ` · commit ${result.commit.sha.slice(0, 10)}` : ""}`,
				"ok",
			);
			$("#history").hidden = true;
			current = null;
			form.hidden = true;
			$("#editor-title").textContent = "Select an article";
			$("#editor-status").textContent = "";
			$("#location").textContent = "No file selected.";
			await Promise.all([loadList(), loadStatus()]);
		} catch (e) {
			notice(e.message, "err");
		}
	});

	$("#new").addEventListener("click", () => {
		notice("");
		fill(null);
	});
	for (const s of root.querySelectorAll(".filters select")) {
		s.addEventListener("change", loadList);
	}

	(async () => {
		try {
			meta = await call("GET", `${API}meta/`);
		} catch (e) {
			notice(e.message, "err");
			return;
		}
		$("#root").textContent = `${meta.root}/<MARKET>/<locale>/articles/*.md`;
		const isGit = meta.source === "git";
		if (isGit) {
			const backend = $("#backend");
			backend.textContent = "📁 Filesystem repository · Git";
			backend.classList.add("git");
		}
		if (isGit || meta.capabilities.includes("index")) {
			const sync = $("#sync");
			sync.hidden = false;
			sync.textContent = isGit ? "Sync with remote" : "Reindex";
			sync.title = isGit
				? "Fetch, fast-forward, push and reindex. Never merges."
				: "Pick up files changed outside the editor.";
			sync.addEventListener("click", async () => {
				try {
					const r = await call("POST", `${API}repository/sync/`);
					const i = r.index || {};
					notice(
						`${isGit ? "Synchronized with the remote. " : ""}Index: ${i.mode} (${i.upserted || 0} updated, ${i.deleted || 0} removed).`,
						"ok",
					);
					await loadList();
				} catch (e) {
					notice(
						e.message + (e.data?.paths ? ` (${e.data.paths.join(", ")})` : ""),
						"err",
					);
				}
				await loadStatus();
			});
		}
		loadStatus();
		const markets = Object.keys(meta.markets);
		const locales = [...new Set(Object.values(meta.markets).flat())];
		options($("#f-market"), markets, "All markets");
		options($("#f-locale"), locales, "All locales");
		options($("#f-category"), meta.categories, "All categories");
		options($("#f-status"), meta.statuses, "Any status");
		options(F.market, markets);
		options(F.status, meta.statuses);
		options(F.category, meta.categories);
		const invalid = Object.keys(meta.invalid_documents || {});
		if (invalid.length)
			notice(`Skipped invalid files: ${invalid.join(", ")}`, "err");
		await loadList();
	})();

	return () => {
		root.remove();
	};
}
