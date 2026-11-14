const bridge = window.AstrBotPluginView;
const statusRoot = document.getElementById('status');
const jobsRoot = document.getElementById('jobs');
const errorRoot = document.getElementById('error');
const updatedRoot = document.getElementById('updated');

const state = { jobs: [], status: null };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

function showError(error) {
  errorRoot.textContent = error?.message || String(error || '请求失败');
  errorRoot.hidden = false;
}

function clearError() {
  errorRoot.hidden = true;
  errorRoot.textContent = '';
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value || 0));
  if (seconds < 60) return `${Math.ceil(seconds)} 秒`;
  return `${Math.floor(seconds / 60)} 分钟`;
}

function renderStatus(status) {
  const cards = [
    ['调度器', status?.scheduler_running ? '运行中' : '未运行'],
    ['会话', `${status?.sessions_count ?? 0}`],
    ['任务', `${status?.jobs_count ?? 0}`],
    ['运行时间', formatDuration(status?.uptime_seconds)],
  ];
  statusRoot.innerHTML = cards
    .map(([label, value]) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`)
    .join('');
}

function renderJobs(jobs) {
  if (!jobs.length) {
    jobsRoot.innerHTML = '<p class="muted empty">当前没有待执行任务。</p>';
    return;
  }

  jobsRoot.innerHTML = jobs
    .map((job) => {
      const session = String(job.id || '');
      const title = job.session_display_name || job.session_name || session;
      const nextRun = job.next_run_time ? new Date(job.next_run_time).toLocaleString() : '未安排';
      const busy = Boolean(job.manual_trigger_in_progress);
      return `
        <article class="job">
          <div class="job-main">
            <strong>${escapeHtml(title)}</strong>
            <span class="mono">${escapeHtml(session)}</span>
            <span class="muted">下一次：${escapeHtml(nextRun)}</span>
          </div>
          <div class="job-actions">
            <button class="button" data-action="trigger" data-session="${encodeURIComponent(session)}" ${busy ? 'disabled' : ''}>${busy ? '处理中' : '立即触发'}</button>
            <button class="button secondary" data-action="reschedule" data-session="${encodeURIComponent(session)}">重新安排</button>
            <button class="button danger" data-action="cancel" data-session="${encodeURIComponent(session)}">取消</button>
          </div>
        </article>`;
    })
    .join('');
}

async function load() {
  clearError();
  try {
    const [status, jobs] = await Promise.all([
      bridge.apiGet('status'),
      bridge.apiGet('jobs'),
    ]);
    state.status = status;
    state.jobs = Array.isArray(jobs?.jobs) ? jobs.jobs : [];
    renderStatus(status);
    renderJobs(state.jobs);
    updatedRoot.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    showError(error);
  }
}

async function operate(action, encodedSession) {
  const session = decodeURIComponent(encodedSession);
  try {
    clearError();
    await bridge.apiPost(`jobs/${encodeURIComponent(session)}/${action}`, {});
    await load();
  } catch (error) {
    showError(error);
  }
}

jobsRoot.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  operate(button.dataset.action, button.dataset.session);
});

document.getElementById('refresh').addEventListener('click', load);
await bridge.ready();
await load();
window.setInterval(load, 5000);
