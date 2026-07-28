<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		cancelOpenMTask,
		createOpenMProject,
		createOpenMTask,
		decideOpenMPermission,
		getOpenMDashboard,
		getOpenMEvents,
		getOpenMPermissions,
		getOpenMProjects,
		getOpenMTasks,
		resumeOpenMTask,
		type OpenMDashboard,
		type OpenMEvent,
		type OpenMPermission,
		type OpenMProject,
		type OpenMTask
	} from '$lib/apis/openm';

	let dashboard: OpenMDashboard | null = null;
	let projects: OpenMProject[] = [];
	let tasks: OpenMTask[] = [];
	let events: OpenMEvent[] = [];
	let permissions: OpenMPermission[] = [];
	let selectedProjectId = '';
	let selectedTaskId = '';
	let loading = true;
	let showProjectModal = false;
	let showTaskModal = false;
	let projectName = '';
	let repositoryUrl = '';
	let defaultBranch = 'main';
	let taskTitle = '';
	let taskPrompt = '';
	let taskModel = 'claude-glm-code';
	let submitting = false;
	let activeInspector: 'changes' | 'terminal' | 'context' = 'changes';
	let activeEventFilter: 'all' | 'agent' | 'tools' | 'files' | 'system' = 'all';
	const eventFilters: Array<typeof activeEventFilter> = ['all', 'agent', 'tools', 'files', 'system'];

	type PhaseState = 'pending' | 'active' | 'complete' | 'attention' | 'failed';
	type ProgressPhase = {
		key: string;
		label: string;
		shortLabel: string;
		state: PhaseState;
	};

	$: selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null;
	$: selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;
	$: projectTasks = selectedProjectId
		? tasks.filter((task) => task.project_id === selectedProjectId)
		: tasks;
	$: pendingPermissions = permissions.filter((permission) => permission.status === 'pending');
	$: latestDiffEvent = [...events].reverse().find((event) => event.type === 'agent.diff.updated');
	$: changedFiles = Array.isArray(latestDiffEvent?.data?.files)
		? (latestDiffEvent?.data.files as string[])
		: [];
	$: currentDiff = typeof latestDiffEvent?.data?.diff === 'string' ? latestDiffEvent.data.diff : '';
	$: additions = currentDiff
		.split('\n')
		.filter((line) => line.startsWith('+') && !line.startsWith('+++')).length;
	$: deletions = currentDiff
		.split('\n')
		.filter((line) => line.startsWith('-') && !line.startsWith('---')).length;
	$: terminalEvents = events.filter((event) => event.type === 'agent.terminal.output');
	$: progressPhases = buildProgressPhases(selectedTask, events, pendingPermissions.length > 0);
	$: completedPhaseCount = progressPhases.filter((phase) => phase.state === 'complete').length;
	$: progressPercent = selectedTask
		? selectedTask.status === 'succeeded'
			? 100
			: Math.max(8, Math.round((completedPhaseCount / progressPhases.length) * 100))
		: 0;
	$: activePhase =
		progressPhases.find((phase) => ['active', 'attention', 'failed'].includes(phase.state)) ??
		progressPhases.at(-1);
	$: latestMeaningfulEvent = [...events]
		.reverse()
		.find((event) => !['task.status.changed', 'agent.text.delta'].includes(event.type));
	$: currentAction = pendingPermissions.length
		? `${pendingPermissions[0].tool_name} の実行許可を待っています`
		: selectedTask?.status === 'succeeded'
			? '実装と検証が完了しました'
			: selectedTask?.status === 'failed'
				? eventBody(
						[...events].reverse().find((event) => event.type === 'agent.failed') ??
							events[events.length - 1]
					)
				: latestMeaningfulEvent
					? eventBody(latestMeaningfulEvent) || eventTitle(latestMeaningfulEvent)
					: selectedTask
						? 'エージェントの最初のアクションを待っています'
						: 'タスクを選択してください';
	$: filteredEvents = events.filter((event) => {
		if (activeEventFilter === 'all') return true;
		if (activeEventFilter === 'agent') {
			return ['agent.text.delta', 'agent.message.completed', 'agent.completed', 'agent.failed'].includes(
				event.type
			);
		}
		if (activeEventFilter === 'tools') {
			return (
				event.type.includes('tool') ||
				event.type === 'agent.terminal.output' ||
				event.type === 'agent.permission.required'
			);
		}
		if (activeEventFilter === 'files') {
			return event.type === 'agent.file.changed' || event.type === 'agent.diff.updated';
		}
		return event.type === 'task.status.changed' || event.type === 'agent.cancelled';
	});

	const token = () => localStorage.token ?? '';
	const setEventFilter = (filter: typeof activeEventFilter) => {
		activeEventFilter = filter;
	};

	const buildProgressPhases = (
		task: OpenMTask | null,
		taskEvents: OpenMEvent[],
		needsAttention: boolean
	): ProgressPhase[] => {
		const phaseDefs = [
			{ key: 'queue', label: 'Task accepted', shortLabel: 'QUEUED' },
			{ key: 'sandbox', label: 'Sandbox ready', shortLabel: 'SANDBOX' },
			{ key: 'inspect', label: 'Codebase inspected', shortLabel: 'INSPECT' },
			{ key: 'implement', label: 'Changes implemented', shortLabel: 'BUILD' },
			{ key: 'verify', label: 'Checks verified', shortLabel: 'VERIFY' },
			{ key: 'deliver', label: 'Ready to review', shortLabel: 'DELIVER' }
		];
		if (!task) return phaseDefs.map((phase) => ({ ...phase, state: 'pending' as PhaseState }));

		const has = (types: string[]) => taskEvents.some((event) => types.includes(event.type));
		const hasInspection = taskEvents.some(
			(event) =>
				event.type === 'agent.tool.requested' &&
				['Glob', 'Grep', 'Read'].includes(String(event.data.tool ?? ''))
		);
		const hasImplementation = has(['agent.file.changed', 'agent.diff.updated']);
		const hasVerification =
			has(['agent.terminal.output']) ||
			taskEvents.some(
				(event) =>
					event.type === 'agent.tool.requested' &&
					String(event.data.tool ?? '') === 'Bash'
			);
		const terminalFailure = terminalEvents.some((event) => Number(event.data.exit_code ?? 0) !== 0);
		const states: PhaseState[] = [
			['queued', 'draft'].includes(task.status) ? 'active' : 'complete',
			task.status === 'preparing'
				? 'active'
				: ['queued', 'draft'].includes(task.status)
					? 'pending'
					: 'complete',
			hasInspection
				? 'complete'
				: task.status === 'running'
					? 'active'
					: ['succeeded', 'failed'].includes(task.status)
						? 'complete'
						: 'pending',
			hasImplementation
				? 'complete'
				: hasInspection && task.status === 'running'
					? 'active'
					: 'pending',
			terminalFailure
				? 'failed'
				: hasVerification && !needsAttention
					? task.status === 'succeeded'
						? 'complete'
						: 'active'
					: needsAttention
						? 'attention'
						: 'pending',
			task.status === 'succeeded'
				? 'complete'
				: task.status === 'failed'
					? 'failed'
					: 'pending'
		];
		return phaseDefs.map((phase, index) => ({ ...phase, state: states[index] }));
	};

	const taskProgress = (task: OpenMTask) =>
		({
			draft: 4,
			queued: 8,
			preparing: 18,
			running: 54,
			waiting_permission: 72,
			waiting_user: 72,
			cancelled: 100,
			succeeded: 100,
			failed: 100,
			timed_out: 100
		})[task.status] ?? 0;

	const elapsedTime = (task: OpenMTask | null) => {
		if (!task?.started_at) return '—';
		const end = task.completed_at ?? Math.floor(Date.now() / 1000);
		const seconds = Math.max(0, end - task.started_at);
		if (seconds < 60) return `${seconds}s`;
		if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
		return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
	};

	const eventKind = (event: OpenMEvent) => {
		if (event.type === 'agent.terminal.output') return 'SHELL';
		if (event.type.includes('tool')) return 'TOOL';
		if (event.type.includes('file') || event.type.includes('diff')) return 'CHANGE';
		if (event.type.includes('permission')) return 'APPROVAL';
		if (event.type.includes('failed')) return 'ISSUE';
		if (event.type.includes('completed')) return 'RESULT';
		if (event.type.startsWith('task.')) return 'STATE';
		return 'AGENT';
	};

	const refresh = async (quiet = false) => {
		try {
			const [nextDashboard, nextProjects, nextTasks] = await Promise.all([
				getOpenMDashboard(token()),
				getOpenMProjects(token()),
				getOpenMTasks(token())
			]);
			dashboard = nextDashboard;
			projects = nextProjects;
			tasks = nextTasks;

			if (!selectedProjectId && projects.length) {
				selectedProjectId = projects[0].id;
			}
			if (!projects.some((project) => project.id === selectedProjectId)) {
				selectedProjectId = projects[0]?.id ?? '';
			}
			if (!tasks.some((task) => task.id === selectedTaskId)) {
				selectedTaskId =
					tasks.find((task) => task.project_id === selectedProjectId)?.id ?? tasks[0]?.id ?? '';
			}
			await refreshTaskDetails();
		} catch (error) {
			if (!quiet)
				toast.error(error instanceof Error ? error.message : 'OpenMを読み込めませんでした');
		} finally {
			loading = false;
		}
	};

	const refreshTaskDetails = async () => {
		if (!selectedTaskId) {
			events = [];
			permissions = [];
			return;
		}
		try {
			[events, permissions] = await Promise.all([
				getOpenMEvents(token(), selectedTaskId),
				getOpenMPermissions(token(), selectedTaskId)
			]);
		} catch {
			events = [];
			permissions = [];
		}
	};

	onMount(() => {
		refresh();
		const interval = window.setInterval(() => refresh(true), 2500);
		return () => window.clearInterval(interval);
	});

	const selectProject = (projectId: string) => {
		selectedProjectId = projectId;
		selectedTaskId = tasks.find((task) => task.project_id === projectId)?.id ?? '';
		refreshTaskDetails();
	};

	const selectTask = (taskId: string) => {
		selectedTaskId = taskId;
		refreshTaskDetails();
	};

	const submitProject = async () => {
		if (!projectName.trim() || !repositoryUrl.trim()) return;
		submitting = true;
		try {
			const project = await createOpenMProject(token(), {
				name: projectName.trim(),
				repository_url: repositoryUrl.trim(),
				default_branch: defaultBranch.trim() || 'main'
			});
			showProjectModal = false;
			projectName = '';
			repositoryUrl = '';
			defaultBranch = 'main';
			selectedProjectId = project.id;
			await refresh();
			toast.success('プロジェクトを接続しました');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'プロジェクトを作成できませんでした');
		} finally {
			submitting = false;
		}
	};

	const submitTask = async () => {
		if (!selectedProjectId || !taskTitle.trim() || !taskPrompt.trim()) return;
		submitting = true;
		try {
			const task = await createOpenMTask(token(), {
				project_id: selectedProjectId,
				title: taskTitle.trim(),
				prompt: taskPrompt.trim(),
				model: taskModel
			});
			showTaskModal = false;
			taskTitle = '';
			taskPrompt = '';
			selectedTaskId = task.id;
			await refresh();
			toast.success('エージェントへタスクを渡しました');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'タスクを作成できませんでした');
		} finally {
			submitting = false;
		}
	};

	const cancelTask = async () => {
		if (!selectedTask) return;
		try {
			await cancelOpenMTask(token(), selectedTask.id);
			await refresh();
			toast.success('タスクを停止しました');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : '停止できませんでした');
		}
	};

	const resumeTask = async () => {
		if (!selectedTask) return;
		try {
			await resumeOpenMTask(token(), selectedTask.id);
			await refresh();
			toast.success('タスクを再開しました');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : '再開できませんでした');
		}
	};

	const decidePermission = async (
		permission: OpenMPermission,
		decision: 'allow_once' | 'allow_for_task' | 'deny'
	) => {
		try {
			await decideOpenMPermission(token(), permission.task_id, permission.id, decision);
			await refresh();
			toast.success(decision === 'deny' ? '操作を拒否しました' : '操作を許可しました');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : '判断を保存できませんでした');
		}
	};

	const statusLabel = (status: string) =>
		({
			draft: '下書き',
			queued: '待機中',
			preparing: '準備中',
			running: '実行中',
			waiting_permission: '許可待ち',
			waiting_user: '入力待ち',
			cancelled: '停止済み',
			succeeded: '完了',
			failed: '失敗',
			timed_out: '時間切れ'
		})[status] ?? status;

	const relativeTime = (unix: number) => {
		const seconds = Math.max(0, Math.floor(Date.now() / 1000 - unix));
		if (seconds < 60) return `${seconds}秒前`;
		if (seconds < 3600) return `${Math.floor(seconds / 60)}分前`;
		if (seconds < 86400) return `${Math.floor(seconds / 3600)}時間前`;
		return `${Math.floor(seconds / 86400)}日前`;
	};

	const eventTitle = (event: OpenMEvent) => {
		const titles: Record<string, string> = {
			'task.status.changed': 'タスク状態を更新',
			'agent.text.delta': 'エージェント',
			'agent.message.completed': '応答を完了',
			'agent.tool.requested': 'ツールを要求',
			'agent.tool.running': 'ツールを実行',
			'agent.tool.result': 'ツール実行結果',
			'agent.permission.required': '操作許可が必要',
			'agent.file.changed': 'ファイルを変更',
			'agent.diff.updated': '差分を更新',
			'agent.terminal.output': 'ターミナル',
			'agent.completed': 'タスク完了',
			'agent.failed': 'タスク失敗',
			'agent.cancelled': 'タスク停止'
		};
		return titles[event.type] ?? event.type;
	};

	const eventBody = (event: OpenMEvent | undefined) => {
		if (!event) return '';
		const data = event.data;
		if (typeof data.text === 'string') return data.text;
		if (typeof data.command === 'string') return `$ ${data.command}`;
		if (typeof data.path === 'string') return data.path;
		if (typeof data.to === 'string') return `${data.from ?? '—'} → ${data.to}`;
		return Object.keys(data).length ? JSON.stringify(data, null, 2) : '';
	};
</script>

<svelte:head>
	<title>OpenM — Agent Workspace</title>
</svelte:head>

<svelte:window
	on:keydown={(event) => {
		if (event.key === 'Escape') {
			showProjectModal = false;
			showTaskModal = false;
		}
	}}
/>

<div class="openm-shell">
	<header class="topbar">
		<div class="brand">
			<div class="brand-mark" aria-hidden="true">
				<span></span><span></span><span></span>
			</div>
			<div>
				<div class="wordmark">OpenM</div>
				<div class="brand-subtitle">PERSONAL AI WORKSPACE</div>
			</div>
		</div>

		<div class="topbar-center">
			<div class="environment-pill">
				<span class="pulse-dot"></span>
				<span>USER SANDBOX</span>
				<strong>{dashboard?.sandbox.status ?? 'CONNECTING'}</strong>
			</div>
			<div class="divider"></div>
			<div class="model-pill"><span>MODEL</span><strong>GLM / LiteLLM</strong></div>
		</div>

		<div class="topbar-actions">
			<button class="icon-button" aria-label="Search">
				<svg viewBox="0 0 24 24"
					><circle cx="11" cy="11" r="7"></circle><path d="m20 20-4-4"></path></svg
				>
			</button>
			<button class="icon-button notification-button" aria-label="Notifications">
				<svg viewBox="0 0 24 24"
					><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path><path d="M10 21h4"
					></path></svg
				>
				{#if dashboard?.waiting_permission}
					<span class="notification-count">{dashboard.waiting_permission}</span>
				{/if}
			</button>
			<div class="avatar">OM</div>
		</div>
	</header>

	<div class="workspace">
		<aside class="rail">
			<nav class="rail-nav" aria-label="OpenM navigation">
				<button class="rail-item active" aria-label="Workspace">
					<svg viewBox="0 0 24 24"
						><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"
						></rect><rect x="3" y="14" width="7" height="7"></rect><rect
							x="14"
							y="14"
							width="7"
							height="7"
						></rect></svg
					>
					<span>WORKSPACE</span>
				</button>
				<button class="rail-item" aria-label="Artifacts">
					<svg viewBox="0 0 24 24"
						><path d="m12 3 9 5-9 5-9-5 9-5Z"></path><path d="m3 12 9 5 9-5"></path><path
							d="m3 16 9 5 9-5"
						></path></svg
					>
					<span>ARTIFACTS</span>
				</button>
				<button class="rail-item" aria-label="Usage">
					<svg viewBox="0 0 24 24"
						><path d="M4 19V9"></path><path d="M10 19V5"></path><path d="M16 19v-7"></path><path
							d="M22 19V2"
						></path></svg
					>
					<span>USAGE</span>
				</button>
			</nav>
			<button class="rail-item settings" aria-label="Settings">
				<svg viewBox="0 0 24 24"
					><circle cx="12" cy="12" r="3"></circle><path
						d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.6v-.1A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3V9.6h.1A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.1A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.4.26.72.61.9 1 .11.25.18.52.2.8V11h.5v4h-.1a1.7 1.7 0 0 0-1.5 0Z"
					></path></svg
				>
				<span>SETTINGS</span>
			</button>
		</aside>

		<aside class="project-panel">
			<div class="panel-heading">
				<div>
					<span class="eyebrow">ENVIRONMENTS</span>
					<h2>Projects</h2>
				</div>
				<button
					class="add-button"
					on:click={() => (showProjectModal = true)}
					aria-label="Add project">+</button
				>
			</div>

			<div class="project-list">
				{#each projects as project}
					<button
						class:active={project.id === selectedProjectId}
						class="project-row"
						on:click={() => selectProject(project.id)}
					>
						<span class="repo-icon">
							<svg viewBox="0 0 24 24"
								><path
									d="M3 5.5A2.5 2.5 0 0 1 5.5 3H10l2 2h6.5A2.5 2.5 0 0 1 21 7.5v9A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5v-11Z"
								></path></svg
							>
						</span>
						<span class="project-copy">
							<strong>{project.name}</strong>
							<small>{project.default_branch}</small>
						</span>
						<span class="task-count"
							>{tasks.filter((task) => task.project_id === project.id).length}</span
						>
					</button>
				{:else}
					<button class="empty-project" on:click={() => (showProjectModal = true)}>
						<span>+</span>
						<strong>Connect repository</strong>
						<small>GitHub URLから開始</small>
					</button>
				{/each}
			</div>

			<div class="sandbox-card">
				<div class="sandbox-card-head">
					<span class="pulse-dot"></span>
					<strong>Personal sandbox</strong>
					<small>READY</small>
				</div>
				<div class="sandbox-meter">
					<span style="width: {Math.min(80, 18 + (dashboard?.running ?? 0) * 24)}%"></span>
				</div>
				<div class="sandbox-meta">
					<span>{dashboard?.sandbox.active_tasks ?? 0} ACTIVE</span>
					<span>ISOLATED</span>
				</div>
			</div>
		</aside>

		<main class="main-stage">
			<section class="stage-header">
				<div class="project-title">
					<div class="breadcrumb">
						<span>WORKSPACE</span><b>/</b><span>{selectedProject?.name ?? 'NO PROJECT'}</span>
					</div>
					<h1>{selectedProject?.name ?? 'Connect your first repository'}</h1>
					{#if selectedProject}
						<p>
							<span>↗</span>{selectedProject.repository_url.replace(/^https?:\/\//, '')}
							<b>•</b>
							<span>⑂</span>{selectedProject.default_branch}
						</p>
					{:else}
						<p>リポジトリを接続すると、専用Sandboxでエージェントを実行できます。</p>
					{/if}
				</div>
				<button
					class="new-task-button"
					disabled={!selectedProject}
					on:click={() => (showTaskModal = true)}
				>
					<span>+</span> NEW TASK <kbd>⌘↵</kbd>
				</button>
			</section>

			<section class="metric-strip">
				<div class="metric">
					<span>RUNNING</span>
					<strong>{dashboard?.running ?? 0}</strong>
					<small class="live"><i></i> LIVE</small>
				</div>
				<div class="metric">
					<span>QUEUED</span>
					<strong>{tasks.filter((task) => task.status === 'queued').length}</strong>
					<small>NEXT UP</small>
				</div>
				<div class="metric">
					<span>NEEDS YOU</span>
					<strong>{dashboard?.waiting_permission ?? 0}</strong>
					<small class:warning={(dashboard?.waiting_permission ?? 0) > 0}>PERMISSION</small>
				</div>
				<div class="metric">
					<span>COMPLETED</span>
					<strong>{dashboard?.completed ?? 0}</strong>
					<small>ALL TIME</small>
				</div>
			</section>

			<section class="command-grid">
				<div class="task-column">
					<div class="column-heading">
						<div>
							<span class="eyebrow">AGENT QUEUE</span>
							<h3>Tasks <b>{projectTasks.length}</b></h3>
						</div>
						<button aria-label="Filter tasks">
							<svg viewBox="0 0 24 24"
								><path d="M4 5h16"></path><path d="M7 12h10"></path><path d="M10 19h4"></path></svg
							>
						</button>
					</div>

					<div class="task-list">
						{#if loading}
							<div class="loading-grid"><span></span><span></span><span></span></div>
						{:else}
							{#each projectTasks as task}
								<button
									class="task-card"
									class:active={task.id === selectedTaskId}
									on:click={() => selectTask(task.id)}
								>
									<div class="task-card-top">
										<span class="status status-{task.status}"
											><i></i>{statusLabel(task.status)}</span
										>
										<small>{relativeTime(task.updated_at)}</small>
									</div>
									<strong>{task.title}</strong>
									<p>{task.prompt}</p>
									<div class="task-progress" aria-label={`${taskProgress(task)}% complete`}>
										<span style={`width: ${taskProgress(task)}%`}></span>
									</div>
									<div class="task-card-foot">
										<span>⑂ {task.branch_name.replace('openm/', '')}</span>
										<span>{taskProgress(task)}%</span>
									</div>
								</button>
							{:else}
								<div class="empty-state">
									<div class="empty-glyph">_</div>
									<strong>No agent tasks</strong>
									<p>実装、調査、テストをエージェントへ依頼します。</p>
									<button disabled={!selectedProject} on:click={() => (showTaskModal = true)}>
										Create first task
									</button>
								</div>
							{/each}
						{/if}
					</div>
				</div>

				<div class="activity-column">
					<div class="column-heading activity-heading">
						<div>
							<span class="eyebrow">LIVE SESSION</span>
							<h3>{selectedTask?.title ?? 'Activity'}</h3>
						</div>
						{#if selectedTask}
							<div class="task-controls">
								<span class="status status-{selectedTask.status}"
									><i></i>{statusLabel(selectedTask.status)}</span
								>
								{#if ['queued', 'preparing', 'running', 'waiting_permission', 'waiting_user'].includes(selectedTask.status)}
									<button class="stop-button" on:click={cancelTask}>■ STOP</button>
								{:else if ['cancelled', 'failed', 'timed_out'].includes(selectedTask.status)}
									<button class="resume-button" on:click={resumeTask}>▶ RESUME</button>
								{/if}
							</div>
						{/if}
					</div>

					{#if selectedTask}
						<section
							class:attention={pendingPermissions.length > 0}
							class:failed={selectedTask.status === 'failed'}
							class="run-overview"
							aria-label="Task progress"
						>
							<div class="run-now">
								<div class="run-state-mark">
									<span>{String(progressPhases.findIndex((phase) => phase === activePhase) + 1).padStart(2, '0')}</span>
								</div>
								<div class="run-now-copy">
									<span class="eyebrow"
										>{pendingPermissions.length ? 'NEEDS YOUR DECISION' : 'NOW WORKING ON'}</span
									>
									<strong>{activePhase?.label ?? statusLabel(selectedTask.status)}</strong>
									<p>{currentAction}</p>
								</div>
								<div class="run-percent">
									<strong>{progressPercent}</strong><span>%</span>
									<small>{elapsedTime(selectedTask)}</small>
								</div>
							</div>

							<div class="phase-rail">
								{#each progressPhases as phase, index}
									<div class="phase phase-{phase.state}">
										<div class="phase-node">
											<span>{phase.state === 'complete' ? '✓' : index + 1}</span>
										</div>
										<div class="phase-copy">
											<strong>{phase.shortLabel}</strong>
											<small>{phase.label}</small>
										</div>
										{#if index < progressPhases.length - 1}<i></i>{/if}
									</div>
								{/each}
							</div>

							<div class="run-facts">
								<div><span>EVENTS</span><strong>{events.length}</strong></div>
								<div><span>FILES TOUCHED</span><strong>{changedFiles.length}</strong></div>
								<div>
									<span>LAST SIGNAL</span>
									<strong>{latestMeaningfulEvent ? relativeTime(latestMeaningfulEvent.timestamp) : '—'}</strong>
								</div>
								<div>
									<span>RUN HEALTH</span>
									<strong
										class:warn={pendingPermissions.length > 0}
										class:error={selectedTask.status === 'failed'}
									>
										{selectedTask.status === 'failed'
											? 'BLOCKED'
											: pendingPermissions.length
												? 'NEEDS YOU'
												: selectedTask.status === 'succeeded'
													? 'VERIFIED'
													: 'ON TRACK'}
									</strong>
								</div>
							</div>
						</section>
					{/if}

					<div class="activity-feed">
						{#each pendingPermissions as permission}
							<div class="permission-card">
								<div class="permission-signal">!</div>
								<div class="permission-content">
									<span>PERMISSION REQUIRED · {permission.risk_level.toUpperCase()}</span>
									<strong>{permission.tool_name}</strong>
									<pre>{JSON.stringify(permission.tool_input_json, null, 2)}</pre>
									<div class="permission-actions">
										<button on:click={() => decidePermission(permission, 'deny')}>DENY</button>
										<button on:click={() => decidePermission(permission, 'allow_once')}
											>ALLOW ONCE</button
										>
										<button
											class="primary"
											on:click={() => decidePermission(permission, 'allow_for_task')}
											>ALLOW FOR TASK</button
										>
									</div>
								</div>
							</div>
						{/each}

						{#if events.length}
							<div class="worklog-toolbar">
								<div>
									<span class="eyebrow">WORKLOG</span>
									<strong>{filteredEvents.length} signals</strong>
								</div>
								<div class="event-filters" aria-label="Filter worklog">
									{#each eventFilters as filter}
										<button
											class:active={activeEventFilter === filter}
											on:click={() => setEventFilter(filter)}
										>
											{filter}
										</button>
									{/each}
								</div>
							</div>
						{/if}

						{#each filteredEvents as event, index}
							<div class="event-row">
								<div class="timeline">
									<span class:event-active={index === filteredEvents.length - 1}></span>
								</div>
								<div class="event-card event-{event.type.replaceAll('.', '-')}">
									<div class="event-meta">
										<div>
											<span class="event-kind kind-{eventKind(event).toLowerCase()}"
												>{eventKind(event)}</span
											>
											<strong>{eventTitle(event)}</strong>
										</div>
										<time
											>{new Date(event.timestamp * 1000).toLocaleTimeString('ja-JP', {
												hour: '2-digit',
												minute: '2-digit',
												second: '2-digit'
											})}</time
										>
									</div>
									{#if eventBody(event)}
										<pre>{eventBody(event)}</pre>
									{/if}
								</div>
							</div>
						{:else}
							<div class="activity-empty">
								<div class="radar"><span></span></div>
								<strong>{selectedTask ? 'Waiting for agent events' : 'Select a task'}</strong>
								<p>
									{selectedTask
										? 'イベントが発生すると、ここへリアルタイムに表示されます。'
										: '左のキューから作業内容を選択してください。'}
								</p>
							</div>
						{/each}
					</div>

					{#if selectedTask}
						<div class="prompt-bar">
							<span>›</span>
							<input aria-label="Follow-up instruction" placeholder="エージェントへ追加の指示…" />
							<button aria-label="Send instruction">↵</button>
						</div>
					{/if}
				</div>

				<aside class="inspector">
					<div class="inspector-tabs">
						<button
							class:active={activeInspector === 'changes'}
							on:click={() => (activeInspector = 'changes')}>CHANGES</button
						>
						<button
							class:active={activeInspector === 'terminal'}
							on:click={() => (activeInspector = 'terminal')}>TERMINAL</button
						>
						<button
							class:active={activeInspector === 'context'}
							on:click={() => (activeInspector = 'context')}>CONTEXT</button
						>
					</div>

					<div class="inspector-body">
						{#if activeInspector === 'changes'}
							<div class="change-summary">
								<span class="eyebrow">WORKTREE</span>
								<strong>{selectedTask?.branch_name ?? 'No task selected'}</strong>
								<p>{selectedTask?.worktree_path ?? 'タスク開始後にworktreeを作成します'}</p>
							</div>
							<div class="file-summary">
								<div><span>FILES</span><strong>{changedFiles.length}</strong></div>
								<div><span>ADDITIONS</span><strong class="plus">+{additions}</strong></div>
								<div><span>DELETIONS</span><strong class="minus">−{deletions}</strong></div>
							</div>
							{#if changedFiles.length}
								<div class="changed-files">
									{#each changedFiles as file}
										<div><span>M</span>{file}</div>
									{/each}
								</div>
								{#if currentDiff}
									<pre class="diff-preview">{currentDiff}</pre>
								{/if}
							{:else}
								<div class="inspector-empty">
									<svg viewBox="0 0 24 24"
										><path d="M4 4h16v16H4z"></path><path d="M8 9h8"></path><path d="M8 13h6"
										></path><path d="M8 17h4"></path></svg
									>
									<strong>No changes yet</strong>
									<p>Agentが編集した差分をここで確認できます。</p>
								</div>
							{/if}
						{:else if activeInspector === 'terminal'}
							<div class="terminal">
								<div class="terminal-line muted">$ openm status</div>
								<div class="terminal-line"><span>workspace</span> user-sandbox</div>
								<div class="terminal-line"><span>project</span> {selectedProject?.name ?? '—'}</div>
								<div class="terminal-line">
									<span>task</span>
									{selectedTask?.id.slice(0, 18) ?? '—'}
								</div>
								{#each terminalEvents as event}
									<div class="terminal-line">
										{String(event.data.output ?? event.data.text ?? '')}
									</div>
								{/each}
								<div class="terminal-line cursor">█</div>
							</div>
						{:else}
							<dl class="context-list">
								<div>
									<dt>MODEL</dt>
									<dd>{selectedTask?.model ?? 'claude-glm-code'}</dd>
								</div>
								<div>
									<dt>MAX TURNS</dt>
									<dd>{selectedTask?.max_turns ?? 40}</dd>
								</div>
								<div>
									<dt>BUDGET</dt>
									<dd>${selectedTask?.max_budget.toFixed(2) ?? '5.00'}</dd>
								</div>
								<div>
									<dt>ACTUAL</dt>
									<dd>${selectedTask?.actual_cost.toFixed(4) ?? '0.0000'}</dd>
								</div>
								<div>
									<dt>ISOLATION</dt>
									<dd>USER + WORKTREE</dd>
								</div>
							</dl>
						{/if}
					</div>
				</aside>
			</section>
		</main>
	</div>
</div>

{#if showProjectModal}
	<div class="modal-backdrop">
		<form class="modal" on:submit|preventDefault={submitProject}>
			<div class="modal-index">01 / PROJECT</div>
			<h2>Connect repository</h2>
			<p>ユーザー専用SandboxへcloneするGitリポジトリを登録します。</p>
			<label>
				<span>PROJECT NAME</span>
				<input bind:value={projectName} placeholder="openm-web" required />
			</label>
			<label>
				<span>REPOSITORY URL</span>
				<input bind:value={repositoryUrl} placeholder="https://github.com/org/repo.git" required />
			</label>
			<label>
				<span>DEFAULT BRANCH</span>
				<input bind:value={defaultBranch} placeholder="main" required />
			</label>
			<div class="modal-actions">
				<button type="button" on:click={() => (showProjectModal = false)}>CANCEL</button>
				<button class="primary" type="submit" disabled={submitting}>
					{submitting ? 'CONNECTING…' : 'CONNECT PROJECT'}
				</button>
			</div>
		</form>
	</div>
{/if}

{#if showTaskModal}
	<div class="modal-backdrop">
		<form class="modal task-modal" on:submit|preventDefault={submitTask}>
			<div class="modal-index">02 / AGENT TASK</div>
			<h2>Delegate a task</h2>
			<p>
				<strong>{selectedProject?.name}</strong> の専用worktreeでClaude Codeエージェントを起動します。
			</p>
			<label>
				<span>TASK TITLE</span>
				<input bind:value={taskTitle} placeholder="認証画面のバグを修正" required />
			</label>
			<label>
				<span>INSTRUCTION</span>
				<textarea
					bind:value={taskPrompt}
					rows="7"
					placeholder="症状、期待する挙動、実行してほしいテストを記述してください。"
					required
				></textarea>
			</label>
			<label>
				<span>MODEL ROUTE</span>
				<select bind:value={taskModel}>
					<option value="claude-glm-code">GLM Code via LiteLLM</option>
					<option value="claude-glm-main">GLM Main via LiteLLM</option>
				</select>
			</label>
			<div class="modal-actions">
				<button type="button" on:click={() => (showTaskModal = false)}>CANCEL</button>
				<button class="primary" type="submit" disabled={submitting}>
					{submitting ? 'QUEUING…' : 'START AGENT'}
				</button>
			</div>
		</form>
	</div>
{/if}

<style>
	:global(body) {
		overflow: hidden;
		background: #0b0d0e;
	}

	:global(.dark body) {
		background: #0b0d0e;
	}

	.openm-shell {
		--ink: #e9ece8;
		--muted: #858c89;
		--line: #262b2a;
		--panel: #111413;
		--panel-raised: #171a19;
		--lime: #c7f36b;
		--amber: #ffb454;
		--red: #ff6b5f;
		--cyan: #69d8da;
		width: 100%;
		height: 100dvh;
		color: var(--ink);
		background: linear-gradient(rgba(255, 255, 255, 0.018) 1px, transparent 1px),
			linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px), #0b0d0e;
		background-size: 32px 32px;
		font-family: 'Archivo', sans-serif;
		overflow: hidden;
	}

	button,
	input,
	textarea,
	select {
		font: inherit;
	}

	button {
		color: inherit;
	}

	svg {
		width: 1.15rem;
		fill: none;
		stroke: currentColor;
		stroke-width: 1.7;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.topbar {
		height: 68px;
		display: grid;
		grid-template-columns: 280px 1fr 280px;
		align-items: center;
		border-bottom: 1px solid var(--line);
		background: rgba(11, 13, 14, 0.94);
		backdrop-filter: blur(18px);
		position: relative;
		z-index: 10;
	}

	.brand {
		height: 100%;
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 0 19px;
		border-right: 1px solid var(--line);
	}

	.brand-mark {
		width: 31px;
		height: 31px;
		border: 1px solid #424a46;
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		align-items: end;
		gap: 3px;
		padding: 6px;
		transform: rotate(-2deg);
	}

	.brand-mark span {
		background: var(--lime);
		height: 50%;
	}

	.brand-mark span:nth-child(2) {
		height: 100%;
	}

	.brand-mark span:nth-child(3) {
		height: 72%;
	}

	.wordmark {
		font-family: 'InstrumentSerif', serif;
		font-size: 25px;
		line-height: 20px;
		letter-spacing: -0.6px;
	}

	.brand-subtitle,
	.eyebrow {
		color: var(--muted);
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		font-weight: 700;
		letter-spacing: 1.45px;
	}

	.brand-subtitle {
		margin-top: 5px;
	}

	.topbar-center,
	.topbar-actions {
		display: flex;
		align-items: center;
	}

	.topbar-center {
		justify-content: center;
		gap: 18px;
	}

	.environment-pill,
	.model-pill {
		display: flex;
		align-items: center;
		gap: 8px;
		font-family: 'JetBrainsMono', monospace;
		font-size: 9px;
		letter-spacing: 0.8px;
	}

	.environment-pill > span:not(.pulse-dot),
	.model-pill span {
		color: var(--muted);
	}

	.environment-pill strong {
		color: var(--lime);
	}

	.pulse-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--lime);
		box-shadow:
			0 0 0 4px rgba(199, 243, 107, 0.1),
			0 0 12px rgba(199, 243, 107, 0.4);
		animation: pulse 2s ease-in-out infinite;
	}

	.divider {
		width: 1px;
		height: 18px;
		background: var(--line);
	}

	.topbar-actions {
		height: 100%;
		justify-content: flex-end;
		gap: 4px;
		padding: 0 17px;
		border-left: 1px solid var(--line);
	}

	.icon-button,
	.add-button,
	.column-heading button {
		border: 0;
		background: transparent;
		cursor: pointer;
	}

	.icon-button {
		width: 36px;
		height: 36px;
		display: grid;
		place-items: center;
		color: #8c9390;
		position: relative;
	}

	.icon-button:hover {
		color: var(--ink);
		background: #171a19;
	}

	.notification-count {
		position: absolute;
		top: 4px;
		right: 2px;
		width: 15px;
		height: 15px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		background: var(--amber);
		color: #15120d;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		font-weight: 900;
	}

	.avatar {
		width: 31px;
		height: 31px;
		display: grid;
		place-items: center;
		margin-left: 8px;
		border-radius: 2px;
		background: #d8dcd7;
		color: #111;
		font-family: 'JetBrainsMono', monospace;
		font-size: 10px;
		font-weight: 800;
	}

	.workspace {
		height: calc(100dvh - 68px);
		display: grid;
		grid-template-columns: 70px 210px minmax(0, 1fr);
	}

	.rail {
		padding: 17px 0;
		border-right: 1px solid var(--line);
		background: rgba(13, 15, 15, 0.88);
		display: flex;
		flex-direction: column;
		justify-content: space-between;
	}

	.rail-nav {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.rail-item {
		width: 100%;
		height: 58px;
		padding: 7px 0;
		border: 0;
		background: transparent;
		color: #69706d;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 5px;
		cursor: pointer;
		position: relative;
	}

	.rail-item span {
		font-family: 'JetBrainsMono', monospace;
		font-size: 6px;
		letter-spacing: 0.65px;
	}

	.rail-item.active {
		color: var(--lime);
	}

	.rail-item.active::before {
		content: '';
		position: absolute;
		left: 0;
		top: 10px;
		bottom: 10px;
		width: 2px;
		background: var(--lime);
		box-shadow: 0 0 10px rgba(199, 243, 107, 0.45);
	}

	.project-panel {
		min-width: 0;
		background: rgba(17, 20, 19, 0.95);
		border-right: 1px solid var(--line);
		display: flex;
		flex-direction: column;
	}

	.panel-heading,
	.column-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.panel-heading {
		height: 85px;
		padding: 0 16px 0 18px;
		border-bottom: 1px solid var(--line);
	}

	.panel-heading h2 {
		margin: 4px 0 0;
		font-size: 17px;
		font-weight: 600;
		letter-spacing: -0.35px;
	}

	.add-button {
		width: 27px;
		height: 27px;
		display: grid;
		place-items: center;
		border: 1px solid #343a37;
		color: #aab0ad;
		font-family: 'JetBrainsMono', monospace;
		font-size: 17px;
	}

	.add-button:hover {
		border-color: var(--lime);
		color: var(--lime);
	}

	.project-list {
		flex: 1;
		padding: 10px;
		overflow-y: auto;
	}

	.project-row {
		width: 100%;
		min-height: 56px;
		padding: 9px;
		border: 1px solid transparent;
		background: transparent;
		display: grid;
		grid-template-columns: 31px 1fr auto;
		gap: 9px;
		align-items: center;
		text-align: left;
		cursor: pointer;
	}

	.project-row:hover {
		background: #171a19;
	}

	.project-row.active {
		border-color: #303632;
		background: #1a1e1c;
		box-shadow: inset 2px 0 var(--lime);
	}

	.repo-icon {
		width: 30px;
		height: 30px;
		display: grid;
		place-items: center;
		border: 1px solid #343a37;
		color: #929995;
	}

	.repo-icon svg {
		width: 15px;
	}

	.project-copy {
		min-width: 0;
	}

	.project-copy strong,
	.project-copy small {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.project-copy strong {
		font-size: 11px;
		font-weight: 600;
	}

	.project-copy small,
	.task-count {
		margin-top: 3px;
		color: #747b77;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
	}

	.task-count {
		margin: 0;
	}

	.empty-project {
		width: 100%;
		padding: 22px 10px;
		border: 1px dashed #343a37;
		background: transparent;
		color: var(--muted);
		cursor: pointer;
	}

	.empty-project span,
	.empty-project strong,
	.empty-project small {
		display: block;
	}

	.empty-project span {
		color: var(--lime);
		font-size: 25px;
	}

	.empty-project strong {
		margin: 7px 0 3px;
		color: var(--ink);
		font-size: 11px;
	}

	.empty-project small {
		font-size: 9px;
	}

	.sandbox-card {
		padding: 13px 15px 16px;
		border-top: 1px solid var(--line);
		background: #0e1110;
	}

	.sandbox-card-head {
		display: grid;
		grid-template-columns: auto 1fr auto;
		align-items: center;
		gap: 8px;
		font-size: 9px;
	}

	.sandbox-card-head .pulse-dot {
		width: 5px;
		height: 5px;
	}

	.sandbox-card-head small,
	.sandbox-meta {
		color: var(--lime);
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 0.7px;
	}

	.sandbox-meter {
		height: 2px;
		margin: 12px 0 7px;
		background: #292e2b;
	}

	.sandbox-meter span {
		display: block;
		height: 100%;
		background: var(--lime);
		transition: width 0.4s ease;
	}

	.sandbox-meta {
		display: flex;
		justify-content: space-between;
		color: #606763;
	}

	.main-stage {
		min-width: 0;
		display: grid;
		grid-template-rows: 85px 64px minmax(0, 1fr);
	}

	.stage-header {
		padding: 0 21px;
		display: flex;
		justify-content: space-between;
		align-items: center;
		border-bottom: 1px solid var(--line);
		background: rgba(13, 15, 15, 0.84);
	}

	.breadcrumb {
		display: flex;
		gap: 7px;
		color: #6c736f;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 1px;
	}

	.breadcrumb b {
		color: #343936;
	}

	.project-title h1 {
		margin: 4px 0 2px;
		font-family: 'InstrumentSerif', serif;
		font-size: clamp(22px, 2vw, 29px);
		font-weight: 400;
		letter-spacing: -0.35px;
		line-height: 1;
	}

	.project-title p {
		max-width: 600px;
		margin: 5px 0 0;
		color: #777e7a;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.project-title p span {
		margin-right: 4px;
		color: #a2aaa5;
	}

	.project-title p b {
		margin: 0 7px;
		color: #3c423f;
	}

	.new-task-button {
		min-width: 145px;
		height: 38px;
		border: 0;
		background: var(--lime);
		color: #12150f;
		font-family: 'JetBrainsMono', monospace;
		font-size: 9px;
		font-weight: 900;
		letter-spacing: 0.8px;
		cursor: pointer;
		box-shadow: 0 7px 24px rgba(199, 243, 107, 0.08);
	}

	.new-task-button:hover:not(:disabled) {
		background: #dcff91;
		transform: translateY(-1px);
	}

	.new-task-button:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}

	.new-task-button > span {
		margin-right: 6px;
	}

	.new-task-button kbd {
		margin-left: 9px;
		padding: 2px 4px;
		border: 1px solid rgba(0, 0, 0, 0.22);
		font-size: 7px;
	}

	.metric-strip {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		border-bottom: 1px solid var(--line);
		background: rgba(15, 17, 17, 0.72);
	}

	.metric {
		padding: 0 17px;
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-rows: 1fr 1fr;
		align-items: end;
		border-right: 1px solid var(--line);
	}

	.metric:last-child {
		border-right: 0;
	}

	.metric > span {
		color: #6e7571;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 1.2px;
	}

	.metric strong {
		grid-row: 1 / 3;
		grid-column: 2;
		align-self: center;
		font-family: 'InstrumentSerif', serif;
		font-size: 28px;
		font-weight: 400;
	}

	.metric small {
		align-self: start;
		color: #555c58;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 0.8px;
	}

	.metric small.live {
		color: var(--lime);
	}

	.metric small.warning {
		color: var(--amber);
	}

	.metric small i {
		display: inline-block;
		width: 4px;
		height: 4px;
		margin-right: 4px;
		border-radius: 50%;
		background: var(--lime);
	}

	.command-grid {
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(220px, 26%) minmax(330px, 1fr) minmax(230px, 29%);
	}

	.task-column,
	.activity-column,
	.inspector {
		min-width: 0;
		min-height: 0;
		background: rgba(12, 14, 14, 0.9);
	}

	.task-column,
	.activity-column {
		border-right: 1px solid var(--line);
	}

	.task-column {
		display: grid;
		grid-template-rows: 55px minmax(0, 1fr);
	}

	.activity-column {
		display: grid;
		grid-template-rows: 55px auto minmax(0, 1fr) auto;
	}

	.column-heading {
		padding: 0 14px;
		border-bottom: 1px solid var(--line);
	}

	.column-heading h3 {
		margin: 3px 0 0;
		font-size: 12px;
		font-weight: 600;
	}

	.column-heading h3 b {
		margin-left: 5px;
		color: #69706c;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
	}

	.column-heading button {
		color: #777e7a;
	}

	.task-list,
	.activity-feed {
		overflow-y: auto;
		scrollbar-width: thin;
		scrollbar-color: #323735 transparent;
	}

	.task-list {
		padding: 8px;
	}

	.task-card {
		width: 100%;
		padding: 12px 12px 10px;
		border: 1px solid transparent;
		border-bottom-color: #222624;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}

	.task-card:hover {
		background: #141716;
	}

	.task-card.active {
		border-color: #343a37;
		background: #171b19;
		box-shadow: inset 2px 0 var(--lime);
	}

	.task-card-top,
	.task-card-foot,
	.event-meta {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.task-card-top > small {
		color: #5e6561;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
	}

	.status {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		color: #909793;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		font-weight: 700;
		letter-spacing: 0.55px;
		text-transform: uppercase;
	}

	.status i {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: currentColor;
	}

	.status-running,
	.status-succeeded {
		color: var(--lime);
	}

	.status-queued,
	.status-preparing {
		color: var(--cyan);
	}

	.status-waiting_permission,
	.status-waiting_user {
		color: var(--amber);
	}

	.status-failed,
	.status-cancelled,
	.status-timed_out {
		color: var(--red);
	}

	.task-card > strong {
		display: block;
		margin: 10px 0 5px;
		font-size: 11px;
		font-weight: 600;
		line-height: 1.3;
	}

	.task-card > p {
		height: 30px;
		margin: 0;
		overflow: hidden;
		color: #727975;
		font-size: 9px;
		line-height: 15px;
	}

	.task-progress {
		height: 2px;
		margin-top: 11px;
		overflow: hidden;
		background: #272c29;
	}

	.task-progress span {
		display: block;
		height: 100%;
		background: linear-gradient(90deg, var(--cyan), var(--lime));
		box-shadow: 0 0 9px rgba(199, 243, 107, 0.25);
		transition: width 0.45s ease;
	}

	.task-card-foot {
		margin-top: 10px;
		color: #555c58;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
	}

	.loading-grid {
		display: grid;
		gap: 8px;
	}

	.loading-grid span {
		height: 98px;
		background: linear-gradient(90deg, #121514, #1a1e1c, #121514);
		background-size: 200% 100%;
		animation: loading 1.4s infinite;
	}

	.empty-state,
	.activity-empty,
	.inspector-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
		color: #6e7571;
	}

	.empty-state {
		min-height: 260px;
		padding: 30px 20px;
	}

	.empty-glyph {
		width: 45px;
		height: 45px;
		display: grid;
		place-items: center;
		border: 1px solid #333936;
		color: var(--lime);
		font-family: 'JetBrainsMono', monospace;
		font-size: 22px;
	}

	.empty-state strong,
	.activity-empty strong,
	.inspector-empty strong {
		margin-top: 15px;
		color: #c3c8c4;
		font-size: 11px;
	}

	.empty-state p,
	.activity-empty p,
	.inspector-empty p {
		max-width: 220px;
		margin: 5px 0 14px;
		font-size: 9px;
		line-height: 1.6;
	}

	.empty-state button {
		padding: 8px 11px;
		border: 1px solid #3c433f;
		background: transparent;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		cursor: pointer;
	}

	.activity-heading {
		padding-right: 11px;
	}

	.run-overview {
		border-bottom: 1px solid var(--line);
		background:
			linear-gradient(120deg, rgba(105, 216, 218, 0.055), transparent 46%),
			#0f1211;
	}

	.run-overview.attention {
		background:
			linear-gradient(120deg, rgba(255, 180, 84, 0.1), transparent 50%),
			#12110e;
	}

	.run-overview.failed {
		background:
			linear-gradient(120deg, rgba(255, 107, 95, 0.1), transparent 50%),
			#130f0e;
	}

	.run-now {
		min-height: 72px;
		padding: 11px 13px 9px;
		display: grid;
		grid-template-columns: 39px minmax(0, 1fr) auto;
		gap: 11px;
		align-items: center;
	}

	.run-state-mark {
		width: 37px;
		height: 37px;
		display: grid;
		place-items: center;
		border: 1px solid rgba(105, 216, 218, 0.45);
		background: rgba(105, 216, 218, 0.08);
		color: var(--cyan);
		font-family: 'JetBrainsMono', monospace;
		font-size: 9px;
		position: relative;
	}

	.run-state-mark::after {
		content: '';
		position: absolute;
		inset: 4px;
		border: 1px solid rgba(105, 216, 218, 0.16);
	}

	.attention .run-state-mark {
		border-color: var(--amber);
		background: rgba(255, 180, 84, 0.08);
		color: var(--amber);
	}

	.failed .run-state-mark {
		border-color: var(--red);
		background: rgba(255, 107, 95, 0.08);
		color: var(--red);
	}

	.run-now-copy {
		min-width: 0;
	}

	.run-now-copy > strong {
		display: block;
		margin-top: 3px;
		font-size: 12px;
		font-weight: 650;
		letter-spacing: -0.15px;
	}

	.run-now-copy p {
		margin: 3px 0 0;
		overflow: hidden;
		color: #8b938e;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		line-height: 1.45;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.run-percent {
		min-width: 53px;
		text-align: right;
	}

	.run-percent strong {
		font-family: 'InstrumentSerif', serif;
		font-size: 28px;
		font-weight: 400;
		line-height: 1;
	}

	.run-percent > span {
		color: var(--cyan);
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
	}

	.run-percent small {
		display: block;
		margin-top: 2px;
		color: #656d68;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
	}

	.phase-rail {
		padding: 4px 13px 10px;
		display: grid;
		grid-template-columns: repeat(6, minmax(0, 1fr));
	}

	.phase {
		min-width: 0;
		position: relative;
	}

	.phase-node {
		width: 18px;
		height: 18px;
		display: grid;
		place-items: center;
		border: 1px solid #3d4440;
		border-radius: 50%;
		background: #101312;
		color: #626a65;
		font-family: 'JetBrainsMono', monospace;
		font-size: 6px;
		position: relative;
		z-index: 2;
	}

	.phase > i {
		position: absolute;
		top: 8px;
		left: 18px;
		right: 0;
		height: 1px;
		background: #303532;
	}

	.phase-complete .phase-node {
		border-color: var(--lime);
		background: var(--lime);
		color: #11150e;
	}

	.phase-complete > i {
		background: var(--lime);
	}

	.phase-active .phase-node {
		border-color: var(--cyan);
		background: rgba(105, 216, 218, 0.12);
		color: var(--cyan);
		box-shadow: 0 0 0 4px rgba(105, 216, 218, 0.07);
		animation: phase-pulse 1.8s ease-in-out infinite;
	}

	.phase-attention .phase-node {
		border-color: var(--amber);
		background: rgba(255, 180, 84, 0.15);
		color: var(--amber);
	}

	.phase-failed .phase-node {
		border-color: var(--red);
		background: rgba(255, 107, 95, 0.14);
		color: var(--red);
	}

	.phase-copy {
		margin-top: 5px;
		padding-right: 3px;
	}

	.phase-copy strong,
	.phase-copy small {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.phase-copy strong {
		color: #626a65;
		font-family: 'JetBrainsMono', monospace;
		font-size: 6px;
		letter-spacing: 0.45px;
	}

	.phase-copy small {
		display: none;
	}

	.phase-active .phase-copy strong {
		color: var(--cyan);
	}

	.phase-complete .phase-copy strong {
		color: #9fb779;
	}

	.phase-attention .phase-copy strong {
		color: var(--amber);
	}

	.phase-failed .phase-copy strong {
		color: var(--red);
	}

	.run-facts {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		border-top: 1px solid #202522;
	}

	.run-facts div {
		min-width: 0;
		padding: 7px 10px;
		border-right: 1px solid #202522;
	}

	.run-facts div:last-child {
		border-right: 0;
	}

	.run-facts span,
	.run-facts strong {
		display: block;
		font-family: 'JetBrainsMono', monospace;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.run-facts span {
		color: #5e6661;
		font-size: 6px;
		letter-spacing: 0.65px;
	}

	.run-facts strong {
		margin-top: 3px;
		color: #b8bfba;
		font-size: 8px;
	}

	.run-facts strong.warn {
		color: var(--amber);
	}

	.run-facts strong.error {
		color: var(--red);
	}

	.task-controls {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.stop-button,
	.resume-button {
		padding: 6px 8px;
		border: 1px solid #3c423f;
		background: transparent;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		cursor: pointer;
	}

	.stop-button {
		color: var(--red);
	}

	.resume-button {
		color: var(--lime);
	}

	.activity-feed {
		padding: 15px 14px 20px;
	}

	.activity-empty {
		height: 100%;
	}

	.radar {
		width: 62px;
		height: 62px;
		border: 1px solid #333936;
		border-radius: 50%;
		display: grid;
		place-items: center;
		position: relative;
		background: radial-gradient(circle, rgba(199, 243, 107, 0.12), transparent 60%);
	}

	.radar::before,
	.radar::after {
		content: '';
		position: absolute;
		background: #333936;
	}

	.radar::before {
		width: 100%;
		height: 1px;
	}

	.radar::after {
		width: 1px;
		height: 100%;
	}

	.radar span {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: var(--lime);
		box-shadow: 0 0 12px var(--lime);
	}

	.permission-card {
		margin-bottom: 14px;
		padding: 12px;
		border: 1px solid rgba(255, 180, 84, 0.55);
		background: rgba(255, 180, 84, 0.06);
		display: grid;
		grid-template-columns: 26px 1fr;
		gap: 10px;
	}

	.permission-signal {
		width: 24px;
		height: 24px;
		display: grid;
		place-items: center;
		border: 1px solid var(--amber);
		color: var(--amber);
		font-family: 'JetBrainsMono', monospace;
		font-weight: 900;
	}

	.permission-content > span {
		color: var(--amber);
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 0.8px;
	}

	.permission-content > strong {
		display: block;
		margin-top: 5px;
		font-size: 11px;
	}

	.permission-content pre,
	.event-card pre {
		white-space: pre-wrap;
		word-break: break-word;
		font-family: 'JetBrainsMono', monospace;
	}

	.permission-content pre {
		max-height: 100px;
		padding: 8px;
		overflow: auto;
		background: rgba(0, 0, 0, 0.28);
		color: #c0c6c2;
		font-size: 8px;
	}

	.permission-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
	}

	.permission-actions button {
		padding: 6px 7px;
		border: 1px solid #494f4c;
		background: transparent;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		cursor: pointer;
	}

	.permission-actions button.primary {
		border-color: var(--amber);
		background: var(--amber);
		color: #17110b;
	}

	.worklog-toolbar {
		margin: 2px 0 12px;
		padding-bottom: 9px;
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 10px;
		border-bottom: 1px solid #252a27;
	}

	.worklog-toolbar > div:first-child strong {
		display: block;
		margin-top: 3px;
		color: #aab1ad;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		font-weight: 500;
	}

	.event-filters {
		display: flex;
		gap: 3px;
	}

	.event-filters button {
		padding: 4px 6px;
		border: 1px solid transparent;
		background: transparent;
		color: #626a65;
		font-family: 'JetBrainsMono', monospace;
		font-size: 6px;
		letter-spacing: 0.3px;
		text-transform: uppercase;
		cursor: pointer;
	}

	.event-filters button:hover {
		color: #aab1ad;
	}

	.event-filters button.active {
		border-color: #3b423e;
		background: #181c1a;
		color: var(--lime);
	}

	.event-row {
		display: grid;
		grid-template-columns: 18px minmax(0, 1fr);
	}

	.timeline {
		position: relative;
	}

	.timeline::after {
		content: '';
		position: absolute;
		top: 13px;
		bottom: -13px;
		left: 4px;
		width: 1px;
		background: #2a2f2c;
	}

	.event-row:last-child .timeline::after {
		display: none;
	}

	.timeline span {
		position: absolute;
		top: 8px;
		left: 1px;
		width: 7px;
		height: 7px;
		border: 1px solid #59605c;
		border-radius: 50%;
		background: #0c0e0e;
	}

	.timeline span.event-active {
		border-color: var(--lime);
		background: var(--lime);
		box-shadow: 0 0 8px rgba(199, 243, 107, 0.45);
	}

	.event-card {
		min-width: 0;
		margin-bottom: 11px;
		padding: 8px 10px;
		border: 1px solid #242927;
		background: #111413;
	}

	.event-meta strong {
		display: inline;
		font-size: 9px;
		font-weight: 600;
	}

	.event-meta > div {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 7px;
	}

	.event-kind {
		flex: none;
		min-width: 42px;
		padding: 3px 4px 2px;
		border: 1px solid #353b38;
		color: #7d8580;
		font-family: 'JetBrainsMono', monospace;
		font-size: 5px;
		font-weight: 800;
		letter-spacing: 0.45px;
		text-align: center;
	}

	.event-kind.kind-change,
	.event-kind.kind-result {
		border-color: rgba(199, 243, 107, 0.38);
		color: var(--lime);
	}

	.event-kind.kind-tool,
	.event-kind.kind-shell {
		border-color: rgba(105, 216, 218, 0.38);
		color: var(--cyan);
	}

	.event-kind.kind-approval {
		border-color: rgba(255, 180, 84, 0.45);
		color: var(--amber);
	}

	.event-kind.kind-issue {
		border-color: rgba(255, 107, 95, 0.5);
		color: var(--red);
	}

	.event-meta time {
		color: #555d58;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
	}

	.event-card pre {
		margin: 7px 0 0;
		color: #a4aba7;
		font-size: 8px;
		line-height: 1.55;
	}

	.event-agent-terminal-output {
		border-left-color: var(--cyan);
		background: #0d1212;
	}

	.event-agent-failed {
		border-left-color: var(--red);
	}

	.prompt-bar {
		min-height: 48px;
		padding: 7px 9px;
		border-top: 1px solid var(--line);
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 7px;
		align-items: center;
		background: #101312;
	}

	.prompt-bar > span {
		color: var(--lime);
		font-family: 'JetBrainsMono', monospace;
	}

	.prompt-bar input {
		height: 32px;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--ink);
		font-size: 9px;
	}

	.prompt-bar button {
		width: 28px;
		height: 28px;
		border: 1px solid #363d39;
		background: #1a1e1c;
		color: var(--lime);
		cursor: pointer;
	}

	.inspector {
		display: grid;
		grid-template-rows: 55px minmax(0, 1fr);
	}

	.inspector-tabs {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		border-bottom: 1px solid var(--line);
	}

	.inspector-tabs button {
		border: 0;
		border-right: 1px solid #202422;
		background: transparent;
		color: #656d68;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 0.65px;
		cursor: pointer;
		position: relative;
	}

	.inspector-tabs button.active {
		color: var(--ink);
		background: #141716;
	}

	.inspector-tabs button.active::after {
		content: '';
		position: absolute;
		bottom: -1px;
		left: 20%;
		right: 20%;
		height: 2px;
		background: var(--lime);
	}

	.inspector-body {
		min-height: 0;
		overflow: auto;
	}

	.change-summary {
		padding: 16px;
		border-bottom: 1px solid var(--line);
	}

	.change-summary strong {
		display: block;
		margin-top: 7px;
		font-family: 'JetBrainsMono', monospace;
		font-size: 9px;
	}

	.change-summary p {
		margin: 5px 0 0;
		color: #666e69;
		font-size: 8px;
		word-break: break-all;
	}

	.file-summary {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		border-bottom: 1px solid var(--line);
	}

	.file-summary div {
		padding: 12px 10px;
		border-right: 1px solid var(--line);
	}

	.file-summary span,
	.file-summary strong {
		display: block;
	}

	.file-summary span {
		color: #626964;
		font-family: 'JetBrainsMono', monospace;
		font-size: 6px;
		letter-spacing: 0.6px;
	}

	.file-summary strong {
		margin-top: 5px;
		font-family: 'JetBrainsMono', monospace;
		font-size: 11px;
	}

	.file-summary .plus {
		color: var(--lime);
	}

	.file-summary .minus {
		color: var(--red);
	}

	.changed-files {
		border-bottom: 1px solid var(--line);
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
	}

	.changed-files div {
		display: flex;
		gap: 9px;
		padding: 10px 12px;
		border-bottom: 1px solid #171c19;
		word-break: break-all;
	}

	.changed-files span {
		color: var(--lime);
	}

	.diff-preview {
		max-height: 360px;
		margin: 0;
		padding: 12px;
		overflow: auto;
		background: #080a0a;
		color: #abb4ae;
		font:
			7px/1.6 'JetBrainsMono',
			monospace;
		white-space: pre-wrap;
	}

	.inspector-empty {
		min-height: 260px;
		padding: 20px;
	}

	.inspector-empty svg {
		width: 29px;
		color: #4e5551;
	}

	.terminal {
		min-height: 100%;
		padding: 16px;
		background: #080a0a;
		color: #aab2ad;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		line-height: 1.8;
	}

	.terminal-line span {
		display: inline-block;
		width: 70px;
		color: var(--lime);
	}

	.terminal-line.muted {
		color: #555d58;
	}

	.terminal-line.cursor {
		margin-top: 8px;
		color: var(--lime);
		animation: blink 1s steps(1) infinite;
	}

	.context-list {
		margin: 0;
	}

	.context-list div {
		padding: 14px;
		border-bottom: 1px solid var(--line);
	}

	.context-list dt {
		color: #5f6762;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 0.8px;
	}

	.context-list dd {
		margin: 6px 0 0;
		color: #bec4c0;
		font-family: 'JetBrainsMono', monospace;
		font-size: 9px;
		word-break: break-all;
	}

	.modal-backdrop {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: grid;
		place-items: center;
		padding: 24px;
		background: rgba(5, 7, 7, 0.78);
		backdrop-filter: blur(8px);
	}

	.modal {
		width: min(500px, 100%);
		padding: 27px;
		border: 1px solid #3b423e;
		background: linear-gradient(135deg, rgba(199, 243, 107, 0.035), transparent 42%), #121514;
		box-shadow: 0 24px 80px rgba(0, 0, 0, 0.55);
	}

	.modal-index {
		color: var(--lime);
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		letter-spacing: 1.2px;
	}

	.modal h2 {
		margin: 8px 0 3px;
		font-family: 'InstrumentSerif', serif;
		font-size: 34px;
		font-weight: 400;
	}

	.modal > p {
		margin: 0 0 22px;
		color: #7d8580;
		font-size: 10px;
		line-height: 1.6;
	}

	.modal label {
		display: block;
		margin-top: 13px;
	}

	.modal label > span {
		display: block;
		margin-bottom: 6px;
		color: #777f7a;
		font-family: 'JetBrainsMono', monospace;
		font-size: 7px;
		letter-spacing: 0.9px;
	}

	.modal input,
	.modal textarea,
	.modal select {
		width: 100%;
		border: 1px solid #343a37;
		outline: 0;
		background: #0b0e0d;
		color: var(--ink);
		font-family: 'JetBrainsMono', monospace;
		font-size: 10px;
	}

	.modal input,
	.modal select {
		height: 41px;
		padding: 0 11px;
	}

	.modal textarea {
		padding: 11px;
		resize: vertical;
		line-height: 1.6;
	}

	.modal input:focus,
	.modal textarea:focus,
	.modal select:focus {
		border-color: var(--lime);
		box-shadow: 0 0 0 2px rgba(199, 243, 107, 0.08);
	}

	.modal-actions {
		display: flex;
		justify-content: flex-end;
		gap: 7px;
		margin-top: 23px;
		padding-top: 17px;
		border-top: 1px solid var(--line);
	}

	.modal-actions button {
		height: 36px;
		padding: 0 13px;
		border: 1px solid #3c433f;
		background: transparent;
		font-family: 'JetBrainsMono', monospace;
		font-size: 8px;
		font-weight: 700;
		cursor: pointer;
	}

	.modal-actions button.primary {
		border-color: var(--lime);
		background: var(--lime);
		color: #11140e;
	}

	.modal-actions button:disabled {
		opacity: 0.5;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 0.6;
		}
		50% {
			opacity: 1;
		}
	}

	@keyframes loading {
		to {
			background-position: -200% 0;
		}
	}

	@keyframes blink {
		50% {
			opacity: 0;
		}
	}

	@keyframes phase-pulse {
		0%,
		100% {
			box-shadow: 0 0 0 3px rgba(105, 216, 218, 0.04);
		}
		50% {
			box-shadow: 0 0 0 5px rgba(105, 216, 218, 0.11);
		}
	}

	@media (max-width: 1120px) {
		.topbar {
			grid-template-columns: 220px 1fr 170px;
		}

		.workspace {
			grid-template-columns: 58px 185px minmax(0, 1fr);
		}

		.command-grid {
			grid-template-columns: 210px minmax(330px, 1fr);
		}

		.inspector {
			display: none;
		}
	}

	@media (max-width: 760px) {
		.topbar {
			grid-template-columns: 1fr auto;
		}

		.topbar-center {
			display: none;
		}

		.topbar-actions {
			border-left: 0;
		}

		.workspace {
			grid-template-columns: 52px minmax(0, 1fr);
		}

		.project-panel {
			display: none;
		}

		.main-stage {
			grid-template-rows: 84px 58px minmax(0, 1fr);
		}

		.stage-header {
			padding: 0 13px;
		}

		.new-task-button {
			min-width: 42px;
			width: 42px;
			font-size: 0;
		}

		.new-task-button span {
			margin: 0;
			font-size: 18px;
		}

		.new-task-button kbd {
			display: none;
		}

		.metric-strip .metric:nth-child(n + 3) {
			display: none;
		}

		.metric-strip {
			grid-template-columns: 1fr 1fr;
		}

		.command-grid {
			grid-template-columns: 1fr;
		}

		.task-column {
			display: none;
		}

		.activity-column {
			border-right: 0;
		}
	}
</style>
