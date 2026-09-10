/* AI Soft-Skills Intelligence Dashboard — frontend logic */

const DATA_URL = "../data/processed/dashboard_data.json";

let DASHBOARD = null;
let charts = {};

async function loadData() {
    try {
        const res = await fetch(DATA_URL);
        if (!res.ok) throw new Error("fetch failed: " + res.status);
        DASHBOARD = await res.json();
    } catch (e) {
        // Fallback for GitHub Pages / file protocol
        try {
            const res = await fetch("data/processed/dashboard_data.json");
            DASHBOARD = await res.json();
        } catch (e2) {
            // Try absolute path for GitHub Pages
            try {
                const res = await fetch("/vigneshs/data/processed/dashboard_data.json");
                DASHBOARD = await res.json();
            } catch (e3) {
                document.body.innerHTML = "<div style='padding:40px;text-align:center'>" +
                    "<h2>No dashboard data found</h2><p>Run the pipeline to generate data.</p></div>";
                return;
            }
        }
    }
    populateFilters();
    renderKPIs();
    renderCharts();
    renderTable();
    renderNewSkills();
    document.getElementById("generated-at").textContent =
        DASHBOARD.generated_at ? new Date(DASHBOARD.generated_at).toLocaleString() : "--";
}

function populateFilters() {
    if (!DASHBOARD) return;

    const skills = DASHBOARD.trends.map(t => t.skill_name).filter(Boolean);
    const industries = DASHBOARD.industry_comparison.map(i => i.industry);
    const countries = [...new Set(DASHBOARD.trends.map(t => t.country).filter(Boolean))];

    const skillSel = document.getElementById("filter-skill");
    [...skills].sort().forEach(s => {
        const opt = document.createElement("option");
        opt.value = s; opt.textContent = s;
        skillSel.appendChild(opt);
    });

    const indSel = document.getElementById("filter-industry");
    [...industries].forEach(i => {
        const opt = document.createElement("option");
        opt.value = i; opt.textContent = i;
        indSel.appendChild(opt);
    });

    const geoSel = document.getElementById("filter-geography");
    [...countries].sort().forEach(c => {
        const opt = document.createElement("option");
        opt.value = c; opt.textContent = c;
        geoSel.appendChild(opt);
    });
}

function currentTrends() {
    if (!DASHBOARD) return [];
    const fSkill = document.getElementById("filter-skill").value;
    const fInd = document.getElementById("filter-industry").value;
    const fGeo = document.getElementById("filter-geography").value;
    const fConf = document.getElementById("filter-confidence").value;

    return DASHBOARD.trends.filter(t => {
        if (fSkill !== "all" && t.skill_name !== fSkill) return false;
        if (fConf !== "all" && t.confidence !== fConf) return false;
        // Geography / industry applied at evidence level; keep all here
        return true;
    });
}

function renderKPIs() {
    if (!DASHBOARD) return;
    document.getElementById("kpi-total").textContent = DASHBOARD.total_skills ?? "--";
    document.getElementById("kpi-emerging").textContent = DASHBOARD.emerging_skills ?? "--";
    document.getElementById("kpi-increasing").textContent = DASHBOARD.increasing_skills ?? "--";
    document.getElementById("kpi-declining").textContent = DASHBOARD.declining_skills ?? "--";
    document.getElementById("kpi-evidence").textContent = DASHBOARD.new_evidence_items ?? "--";
    document.getElementById("kpi-sources").textContent = DASHBOARD.sources_analyzed ?? "--";
    document.getElementById("kpi-industries").textContent = DASHBOARD.industries_tracked ?? "--";
    document.getElementById("kpi-countries").textContent = DASHBOARD.countries_tracked ?? "--";
}

function renderCharts() {
    if (!DASHBOARD) return;
    const trends = [...currentTrends()].sort((a, b) => b.emerging_score - a.emerging_score);
    const top = trends.slice(0, 10);

    // 1. Top emerging skills
    renderEmergingChart(top);

    // 2. Demand growth (YoY)
    renderGrowthChart(trends.filter(t => t.yoy_growth != null).slice(0, 10));

    // 3. 12-month trend (indexed line chart)
    renderTrendChart();

    // 4. Skill share comparison
    renderShareChart(top);

    // 5. Industry comparison
    renderIndustryChart();

    // 6. Confidence
    renderConfidenceChart();
}

function renderEmergingChart(items) {
    const labels = items.map(i => i.skill_name);
    const data = items.map(i => i.emerging_score);
    const ctx = document.getElementById("chart-emerging").getContext("2d");
    if (charts.emerging) charts.emerging.destroy();
    charts.emerging = new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Emerging Score",
                data,
                backgroundColor: data.map(v => v >= 0.5 ? "rgba(56,178,172,0.8)" : "rgba(43,108,176,0.6)"),
                borderRadius: 6,
            }]
        },
        options: {
            indexAxis: "y",
            responsive: true,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: c => `Score: ${c.raw.toFixed(3)}` } }
            },
            scales: { x: { min: 0, max: 1 } }
        }
    });
}

function renderGrowthChart(items) {
    if (!items.length) {
        document.getElementById("chart-growth").getContext("2d");
        return;
    }
    const ctx = document.getElementById("chart-growth").getContext("2d");
    if (charts.growth) charts.growth.destroy();
    charts.growth = new Chart(ctx, {
        type: "bar",
        data: {
            labels: items.map(i => i.skill_name),
            datasets: [{
                label: "YoY Growth %",
                data: items.map(i => i.yoy_growth),
                backgroundColor: items.map(i => i.yoy_growth >= 0 ? "rgba(56,161,105,0.8)" : "rgba(229,62,62,0.8)"),
                borderRadius: 6,
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: c => `${c.raw != null ? c.raw.toFixed(1) : "n/a"}%` } }
            }
        }
    });
}

function renderTrendChart() {
    const ctx = document.getElementById("chart-trend").getContext("2d");
    if (charts.trend) charts.trend.destroy();

    if (!DASHBOARD.monthly_data || !DASHBOARD.monthly_data.length) {
        return;
    }

    // Aggregate all skills into a single indexed series + average
    const monthMap = {};
    DASHBOARD.monthly_data.forEach(entry => {
        (entry.series || []).forEach(pt => {
            if (!monthMap[pt.month]) monthMap[pt.month] = [];
            monthMap[pt.month].push(pt.demand_index || 0);
        });
    });

    const months = Object.keys(monthMap).sort();
    const avg = months.map(m => {
        const vals = monthMap[m];
        return vals.reduce((a, b) => a + b, 0) / vals.length;
    });

    // Index to 100 at first month
    const base = avg.length ? avg[0] || 1 : 1;
    const indexed = avg.map(v => base ? (v / base) * 100 : 0);

    charts.trend = new Chart(ctx, {
        type: "line",
        data: {
            labels: months,
            datasets: [{
                label: "Demand Index (base = 100)",
                data: indexed,
                borderColor: "rgba(43,108,176,0.9)",
                backgroundColor: "rgba(43,108,176,0.1)",
                fill: true,
                tension: 0.3,
                pointRadius: 3,
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: true, position: "top" } },
            scales: {
                y: { beginAtZero: false },
                x: { ticks: { maxTicksLimit: 12 } }
            }
        }
    });
}

function renderShareChart(items) {
    const ctx = document.getElementById("chart-share").getContext("2d");
    if (charts.share) charts.share.destroy();
    if (!items.length) return;

    charts.share = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: items.map(i => i.skill_name),
            datasets: [{
                label: "Observation Share",
                data: items.map(i => i.emerging_score),
                backgroundColor: [
                    "#f6ad55", "#ed8936", "#ecc94b", "#48bb78", "#38b2ac",
                    "#4299e1", "#667eea", "#9f7aea", "#ed64a6", "#fc8181"
                ],
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: "right" },
                tooltip: { callbacks: { label: c => `${c.label}: ${(c.raw*100).toFixed(1)}%` } }
            }
        }
    });
}

function renderIndustryChart() {
    const ctx = document.getElementById("chart-industry").getContext("2d");
    if (charts.industry) charts.industry.destroy();
    if (!DASHBOARD.industry_comparison || !DASHBOARD.industry_comparison.length) return;

    charts.industry = new Chart(ctx, {
        type: "bar",
        data: {
            labels: DASHBOARD.industry_comparison.map(i => i.industry),
            datasets: [{
                label: "% of Observations",
                data: DASHBOARD.industry_comparison.map(i => i.percentage),
                backgroundColor: "rgba(56,178,172,0.75)",
                borderRadius: 6,
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, max: 100, ticks: { callback: v => v + "%" } } }
        }
    });
}

function renderConfidenceChart() {
    const ctx = document.getElementById("chart-confidence").getContext("2d");
    if (charts.confidence) charts.confidence.destroy();
    const conf = DASHBOARD.evidence_confidence || { high: 0, medium: 0, low: 0 };

    charts.confidence = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: ["High", "Medium", "Low"],
            datasets: [{
                data: [conf.high || 0, conf.medium || 0, conf.low || 0],
                backgroundColor: ["#38a169", "#ecc94b", "#e53e3e"],
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { position: "right" } }
        }
    });
}

function renderTable() {
    const tbody = document.getElementById("skills-table-body");
    tbody.innerHTML = "";
    if (!DASHBOARD) return;

    const rows = currentTrends().sort((a, b) => b.emerging_score - a.emerging_score);
    rows.forEach(t => {
        const tr = document.createElement("tr");
        const fmt = v => (v != null && !isNaN(v)) ? v.toFixed(1) + "%" : "--";
        tr.innerHTML = `
            <td>${escapeHtml(t.skill_name)}</td>
            <td>${t.emerging_score != null ? t.emerging_score.toFixed(3) : "--"}</td>
            <td>${fmt(t.yoy_growth)}</td>
            <td>${fmt(t.mom_growth)}</td>
            <td>${fmt(t.rolling_12m_change)}</td>
            <td>${(t.skill_share != null && !isNaN(t.skill_share)) ? t.skill_share.toFixed(1) + "%" : "--"}</td>
            <td><span class="badge badge-${t.confidence || "low"}">${escapeHtml(t.confidence || "low")}</span></td>
            <td>${escapeHtml(t.evidence_type || "qualitative")}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderNewSkills() {
    const container = document.getElementById("new-skills-list");
    const empty = document.getElementById("new-skills-empty");
    container.innerHTML = "";
    if (DASHBOARD && DASHBOARD.new_skills_detected && DASHBOARD.new_skills_detected.length) {
        empty.style.display = "none";
        DASHBOARD.new_skills_detected.forEach(s => {
            const div = document.createElement("div");
            div.textContent = s;
            container.appendChild(div);
        });
    } else {
        empty.style.display = "block";
    }
}

let sortDirection = 1;
function sortTable(colIdx) {
    sortDirection *= -1;
    const tbody = document.getElementById("skills-table-body");
    const rows = Array.from(tbody.rows);
    rows.sort((a, b) => {
        const av = a.cells[colIdx].textContent;
        const bv = b.cells[colIdx].textContent;
        const an = parseFloat(av);
        const bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return (an - bn) * sortDirection;
        return av.localeCompare(bv) * sortDirection;
    });
    rows.forEach(r => tbody.appendChild(r));
}

function applyFilters() {
    renderTable();
    renderCharts();
}

function exportCSV() {
    if (!DASHBOARD) return;
    const rows = [["Skill", "Emerging Score", "YoY Growth %", "Confidence", "Evidence Type"]];
    DASHBOARD.trends.forEach(t => {
        rows.push([t.skill_name, t.emerging_score, t.yoy_growth, t.confidence, t.evidence_type]);
    });
    const csv = rows.map(r => r.map(c => `"${String(c == null ? "" : c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "softskills_trends.csv";
    a.click();
    URL.revokeObjectURL(url);
}

function showSources() {
    const modal = document.getElementById("source-modal");
    const content = document.getElementById("source-modal-content");
    content.innerHTML = `
        <p><strong>Data provenance:</strong></p>
        <p>Skills are scored via a weighted Emerging Skill Score model with weights:
        demand growth (30%), hiring frequency (25%), cross-industry (15%), cross-country (10%),
        employer/research evidence (10%), recency (5%), source reliability (5%).</p>
        <p><strong>Evidence types:</strong></p>
        <ul>
            <li><strong>Observed</strong> — directly reported by source</li>
            <li><strong>Calculated</strong> — derived from source data</li>
            <li><strong>Estimated</strong> — modelled</li>
            <li><strong>Qualitative</strong> — text/research supported</li>
        </ul>
        <p>Report window: rolling 12 months. Numbers are never fabricated from insufficient data.</p>
    `;
    modal.style.display = "block";
}

function closeModal() {
    document.getElementById("source-modal").style.display = "none";
}

function escapeHtml(s) {
    if (!s) return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
}

window.onclick = function(e) {
    const modal = document.getElementById("source-modal");
    if (e.target === modal) modal.style.display = "none";
};

document.addEventListener("DOMContentLoaded", loadData);
