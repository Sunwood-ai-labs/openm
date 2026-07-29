<script lang="ts">
	import { onMount, tick } from 'svelte';
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
	let prompt = '';
	let taskModel = 'claude-glm-code';
	let loading = true;
	let submitting = false;
	let showProjectModal = false;
	let showThreads = false;
	let showInspector = false;
	let projectName = '';
	let repositoryUrl = '';
	let defaultBranch = 'main';
	let inspectorTab: 'changes' | 'terminal' | 'context' = 'changes';
	let composer: HTMLTextAreaElement;
	let messages: HTMLDivElement;

	type PhaseState = 'pending' | 'active' | 'complete' | 'attention' | 'failed';
	type Phase = { label: string; state: PhaseState };

	$: selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null;
	$: selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;
	$: projectTasks = selectedProjectId
		? tasks.filter((task) => task.project_id === selectedProjectId)
		: tasks;
	$: pendingPermissions = permissions.filter((permission) => permission.status === 'pending');
	$: diffEvent = [...events].reverse().find((event) => event.type === 'agent.diff.updated');
	$: changedFiles = Array.isArray(diffEvent?.data?.files) ? (diffEvent?.data.files as string[]) : [];
	$: currentDiff = typeof diffEvent?.data?.diff === 'string' ? diffEvent.data.diff : '';
	$: terminalEvents = events.filter((event) => event.type === 'agent.terminal.output');
	$: activityEvents = events.filter(
		(event) => !['agent.text.delta', 'agent.message.completed'].includes(event.type)
	);
	$: resultEvent = [...events]
		.reverse()
		.find((event) => ['agent.message.completed', 'agent.completed', 'agent.failed'].includes(event.type));
	$: phases = buildPhases(selectedTask, events, pendingPermissions.length > 0);
	$: progress = selectedTask
		? selectedTask.status === 'succeeded'
			? 100
			: Math.max(8, Math.round((phases.filter((phase) => phase.state === 'complete').length / 6) * 100))
		: 0;
	$: currentAction = getCurrentAction();

	const token = () => localStorage.token ?? '';

	const refreshDetails = async () => {
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
			if (!projects.some((project) => project.id === selectedProjectId)) {
				selectedProjectId = projects[0]?.id ?? '';
			}
			if (!tasks.some((task) => task.id === selectedTaskId)) {
				selectedTaskId =
					tasks.find((task) => task.project_id === selectedProjectId)?.id ?? tasks[0]?.id ?? '';
			}
			await refreshDetails();
		} catch (error) {
			if (!quiet) toast.error(error instanceof Error ? error.message : 'OpenMを読み込めませんでした');
		} finally {
			loading = false;
		}
	};

	onMount(() => {
		refresh();
		const interval = window.setInterval(() => refresh(true), 2500);
		return () => window.clearInterval(interval);
	});

	const selectProject = async (projectId: string) => {
		selectedProjectId = projectId;
		selectedTaskId = tasks.find((task) => task.project_id === projectId)?.id ?? '';
		showThreads = false;
		await refreshDetails();
	};

	const selectTask = async (taskId: string) => {
		selectedTaskId = taskId;
		showThreads = false;
		await refreshDetails();
		await tick();
		messages?.scrollTo({ top: 0, behavior: 'smooth' });
	};

	const startNewTask = async () => {
		selectedTaskId = '';
		events = [];
		permissions = [];
		showThreads = false;
		await tick();
		composer?.focus();
	};

	const submitTask = async () => {
		const cleanPrompt = prompt.trim();
		if (!selectedProjectId) {
			showProjectModal = true;
			return;
		}
		if (!cleanPrompt || submitting) return;
		submitting = true;
		try {
			const firstLine = cleanPrompt.split('\n')[0].replace(/^#+\s*/, '');
			const task = await createOpenMTask(token(), {
				project_id: selectedProjectId,
				title: firstLine.slice(0, 64) || '新しいタスク',
				prompt: cleanPrompt,
				model: taskModel
			});
			prompt = '';
			selectedTaskId = task.id;
			await refresh();
			await tick();
			messages?.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'タスクを開始できませんでした');
		} finally {
			submitting = false;
		}
	};

	const submitProject = async () => {
		if (!projectName.trim() || !repositoryUrl.trim() || submitting) return;
		submitting = true;
		try {
			const project = await createOpenMProject(token(), {
				name: projectName.trim(),
				repository_url: repositoryUrl.trim(),
				default_branch: defaultBranch.trim() || 'main'
			});
			selectedProjectId = project.id;
			showProjectModal = false;
			projectName = '';
			repositoryUrl = '';
			defaultBranch = 'main';
			await refresh();
			await tick();
			composer?.focus();
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'プロジェクトを接続できませんでした');
		} finally {
			submitting = false;
		}
	};

	const cancelTask = async () => {
		if (!selectedTask) return;
		try {
			await cancelOpenMTask(token(), selectedTask.id);
			await refresh();
		} catch (error) {
			toast.error(error instanceof Error ? error.message : '停止できませんでした');
		}
	};

	const resumeTask = async () => {
		if (!selectedTask) return;
		try {
			await resumeOpenMTask(token(), selectedTask.id);
			await refresh();
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
		} catch (error) {
			toast.error(error instanceof Error ? error.message : '判断を保存できませんでした');
		}
	};

	const statusLabel = (status: string) =>
		({
			draft: '下書き',
			queued: '待機中',
			preparing: '環境を準備中',
			running: '作業中',
			waiting_permission: '承認待ち',
			waiting_user: '入力待ち',
			cancelled: '停止済み',
			succeeded: '完了',
			failed: '失敗',
			timed_out: '時間切れ'
		})[status] ?? status;

	const relativeTime = (unix: number) => {
		const seconds = Math.max(0, Math.floor(Date.now() / 1000 - unix));
		if (seconds < 60) return 'たった今';
		if (seconds < 3600) return `${Math.floor(seconds / 60)}分前`;
		if (seconds < 86400) return `${Math.floor(seconds / 3600)}時間前`;
		return `${Math.floor(seconds / 86400)}日前`;
	};

	const elapsedTime = (task: OpenMTask | null) => {
		if (!task?.started_at) return '—';
		const seconds = Math.max(0, (task.completed_at ?? Math.floor(Date.now() / 1000)) - task.started_at);
		if (seconds < 60) return `${seconds}秒`;
		if (seconds < 3600) return `${Math.floor(seconds / 60)}分 ${seconds % 60}秒`;
		return `${Math.floor(seconds / 3600)}時間 ${Math.floor((seconds % 3600) / 60)}分`;
	};

	const eventLabel = (event: OpenMEvent) => {
		if (event.type === 'agent.tool.requested') return `${String(event.data.tool ?? 'ツール')}を使用`;
		if (event.type === 'agent.tool.running') return `${String(event.data.tool ?? 'ツール')}を実行中`;
		if (event.type === 'agent.tool.result') return `${String(event.data.tool ?? 'ツール')}が完了`;
		if (event.type === 'agent.file.changed') return `${String(event.data.path ?? 'ファイル')}を変更`;
		if (event.type === 'agent.diff.updated') return '変更内容を更新';
		if (event.type === 'agent.terminal.output') return 'コマンドを実行';
		if (event.type === 'agent.permission.required') return '操作の承認が必要';
		if (event.type === 'agent.completed') return 'タスクを完了';
		if (event.type === 'agent.failed') return 'タスクで問題が発生';
		if (event.type === 'agent.cancelled') return 'タスクを停止';
		if (event.type === 'task.status.changed') return statusLabel(String(event.data.to ?? ''));
		return event.type;
	};

	const eventDetail = (event: OpenMEvent | undefined) => {
		if (!event) return '';
		if (typeof event.data.text === 'string') return event.data.text;
		if (typeof event.data.command === 'string') return `$ ${event.data.command}`;
		if (typeof event.data.path === 'string') return event.data.path;
		if (typeof event.data.output === 'string') return event.data.output;
		return '';
	};

	const getCurrentAction = () => {
		if (!selectedTask) return '';
		if (pendingPermissions.length) return `${pendingPermissions[0].tool_name} の実行許可を待っています`;
		if (selectedTask.status === 'succeeded') return '実装と検証が完了しました';
		if (selectedTask.status === 'failed') return eventDetail(resultEvent) || '実行中に問題が発生しました';
		const latest = [...activityEvents]
			.reverse()
			.find((event) => !['task.status.changed', 'agent.diff.updated'].includes(event.type));
		return latest ? eventLabel(latest) : 'エージェントを起動しています';
	};

	const buildPhases = (
		task: OpenMTask | null,
		taskEvents: OpenMEvent[],
		needsAttention: boolean
	): Phase[] => {
		const labels = ['受付', '環境準備', '調査', '実装', '検証', '完了'];
		if (!task) return labels.map((label) => ({ label, state: 'pending' }));
		const hasTool = (tools: string[]) =>
			taskEvents.some(
				(event) =>
					event.type === 'agent.tool.requested' && tools.includes(String(event.data.tool ?? ''))
			);
		const changed = taskEvents.some((event) =>
			['agent.file.changed', 'agent.diff.updated'].includes(event.type)
		);
		const verified =
			hasTool(['Bash']) || taskEvents.some((event) => event.type === 'agent.terminal.output');
		const states: PhaseState[] = [
			['draft', 'queued'].includes(task.status) ? 'active' : 'complete',
			task.status === 'preparing'
				? 'active'
				: ['draft', 'queued'].includes(task.status)
					? 'pending'
					: 'complete',
			hasTool(['Glob', 'Grep', 'Read'])
				? 'complete'
				: task.status === 'running'
					? 'active'
					: 'pending',
			changed ? 'complete' : task.status === 'running' ? 'active' : 'pending',
			task.status === 'failed'
				? 'failed'
				: task.status === 'succeeded'
					? 'complete'
					: needsAttention
						? 'attention'
						: verified
							? 'active'
							: 'pending',
			task.status === 'succeeded'
				? 'complete'
				: task.status === 'failed'
					? 'failed'
					: 'pending'
		];
		return labels.map((label, index) => ({ label, state: states[index] }));
	};

	const autoGrow = (event: Event) => {
		const element = event.currentTarget as HTMLTextAreaElement;
		element.style.height = 'auto';
		element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
	};
</script>

<svelte:head>
	<title>OpenM — AI coding workspace</title>
</svelte:head>

<svelte:window
	on:keydown={(event) => {
		if (event.key === 'Escape') {
			showProjectModal = false;
			showThreads = false;
			showInspector = false;
		}
	}}
/>

<div class="openm-chat">
	<header class="chat-header">
		<div class="header-left">
			<button class="icon-button mobile-only" on:click={() => (showThreads = !showThreads)} aria-label="タスク一覧">
				<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10" /></svg>
			</button>
			<div class="agent-mark"><span></span><span></span><span></span></div>
			<div class="title-stack">
				<strong>OpenM</strong>
				<span>{selectedProject?.name ?? 'AI coding workspace'}</span>
			</div>
		</div>
		<div class="header-center">
			<span class="presence"></span>
			<span>{dashboard?.sandbox.status === 'ready' ? 'Sandbox ready' : 'Connecting'}</span>
			<i></i>
			<span>GLM via LiteLLM</span>
		</div>
		<div class="header-actions">
			{#if selectedTask}
				<button class="artifact-button" on:click={() => (showInspector = !showInspector)}>
					<svg viewBox="0 0 24 24"><path d="M4 4h16v16H4zM9 4v16" /></svg>
					<span>{changedFiles.length ? `${changedFiles.length} files` : 'Workspace'}</span>
				</button>
			{/if}
			<button class="new-button" disabled={!selectedProject} on:click={startNewTask}>
				<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
				<span>新しいタスク</span>
			</button>
		</div>
	</header>

	<div class="app-body">
		{#if showThreads}<button class="mobile-scrim" on:click={() => (showThreads = false)} aria-label="閉じる"></button>{/if}
		<aside class:open={showThreads} class="thread-sidebar">
			<div class="project-switcher">
				<label for="project">PROJECT</label>
				<div class="select-wrap">
					<select id="project" bind:value={selectedProjectId} on:change={() => selectProject(selectedProjectId)}>
						{#each projects as project}
							<option value={project.id}>{project.name}</option>
						{/each}
					</select>
					<svg viewBox="0 0 24 24"><path d="m8 10 4 4 4-4" /></svg>
				</div>
				<button class="connect-button" on:click={() => (showProjectModal = true)} aria-label="リポジトリを接続">+</button>
			</div>

			<button class="sidebar-new" disabled={!selectedProject} on:click={startNewTask}>
				<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
				新しいタスク
			</button>

			<div class="thread-label"><span>RECENT</span><b>{projectTasks.length}</b></div>
			<div class="thread-list">
				{#if loading}
					<div class="skeleton"></div><div class="skeleton short"></div>
				{:else}
					{#each projectTasks as task}
						<button class:active={task.id === selectedTaskId} class="thread" on:click={() => selectTask(task.id)}>
							<span class="thread-status status-{task.status}"></span>
							<span class="thread-copy">
								<strong>{task.title}</strong>
								<small>{statusLabel(task.status)} · {relativeTime(task.updated_at)}</small>
							</span>
						</button>
					{:else}
						<div class="no-threads">最初の依頼を入力すると、ここに会話が保存されます。</div>
					{/each}
				{/if}
			</div>
			<div class="sandbox-note">
				<span class="presence"></span>
				<div><strong>Personal sandbox</strong><small>ユーザーごとに分離</small></div>
			</div>
		</aside>

		<main class:inspector-open={showInspector && selectedTask} class="conversation">
			<div class="messages" bind:this={messages}>
				{#if !selectedTask}
					<section class="empty-chat">
						<div class="empty-mark"><span></span><span></span><span></span></div>
						<h1>何を作りますか？</h1>
						<p>
							リポジトリを読み、実装し、テストまで進めます。<br />
							作業中の判断や変更ファイルは、この会話にそのまま表示されます。
						</p>
						<div class="suggestions">
							<button on:click={() => (prompt = 'このリポジトリを調査して、改善すべき点を3つ提案して')}>
								<span>01</span>リポジトリを調査
							</button>
							<button on:click={() => (prompt = 'READMEを改善して、初めての人でも起動できるようにして')}>
								<span>02</span>READMEを改善
							</button>
							<button on:click={() => (prompt = 'テストを実行して、失敗している箇所を修正して')}>
								<span>03</span>テストを修正
							</button>
						</div>
					</section>
				{:else}
					<div class="conversation-inner">
						<div class="task-meta">
							<span>{selectedProject?.name}</span>
							<i>/</i>
							<span>{selectedTask.branch_name.replace('openm/', '')}</span>
						</div>

						<article class="user-message">
							<div class="user-avatar">YOU</div>
							<div>
								<div class="message-author"><strong>あなた</strong><time>{relativeTime(selectedTask.created_at)}</time></div>
								<p>{selectedTask.prompt}</p>
							</div>
						</article>

						<article class="agent-message">
							<div class="openm-avatar"><span></span><span></span><span></span></div>
							<div class="agent-content">
								<div class="message-author">
									<strong>OpenM</strong>
									<span class="model-name">{selectedTask.model}</span>
								</div>

								<section class:attention={pendingPermissions.length > 0} class="run-card">
									<div class="run-card-head">
										<div class="run-copy">
											<span class="run-status status-{selectedTask.status}">
												<i></i>{statusLabel(selectedTask.status)}
											</span>
											<h2>{currentAction}</h2>
											<p>{elapsedTime(selectedTask)} · {events.length}件のアクティビティ</p>
										</div>
										<strong class="progress-number">{progress}<small>%</small></strong>
									</div>
									<div class="progress-track"><span style={`width:${progress}%`}></span></div>
									<div class="phase-list">
										{#each phases as phase}
											<div class="phase phase-{phase.state}">
												<span>{phase.state === 'complete' ? '✓' : ''}</span>
												<small>{phase.label}</small>
											</div>
										{/each}
									</div>
									{#if ['queued', 'preparing', 'running', 'waiting_permission', 'waiting_user'].includes(selectedTask.status)}
										<button class="text-action danger" on:click={cancelTask}>実行を停止</button>
									{:else if ['cancelled', 'failed', 'timed_out'].includes(selectedTask.status)}
										<button class="text-action" on:click={resumeTask}>もう一度実行</button>
									{/if}
								</section>

								{#each pendingPermissions as permission}
									<section class="approval-card">
										<div class="approval-icon">!</div>
										<div>
											<span>あなたの確認が必要です</span>
											<h3>{permission.tool_name} を実行してよいですか？</h3>
											<pre>{JSON.stringify(permission.tool_input_json, null, 2)}</pre>
											<div class="approval-actions">
												<button on:click={() => decidePermission(permission, 'deny')}>拒否</button>
												<button on:click={() => decidePermission(permission, 'allow_once')}>今回のみ許可</button>
												<button class="primary" on:click={() => decidePermission(permission, 'allow_for_task')}>このタスクで許可</button>
											</div>
										</div>
									</section>
								{/each}

								{#if activityEvents.length}
									<details class="activity-card" open={selectedTask.status !== 'succeeded'}>
										<summary>
											<span class="activity-symbol">
												{selectedTask.status === 'succeeded' ? '✓' : '⋯'}
											</span>
											<div>
												<strong>作業の詳細</strong>
												<small>{activityEvents.length}件のステップ</small>
											</div>
											<svg viewBox="0 0 24 24"><path d="m8 10 4 4 4-4" /></svg>
										</summary>
										<div class="activity-list">
											{#each activityEvents as event, index}
												<div class="activity-row">
													<div class="activity-line"><span class:live={index === activityEvents.length - 1}></span></div>
													<div>
														<strong>{eventLabel(event)}</strong>
														{#if eventDetail(event)}<pre>{eventDetail(event)}</pre>{/if}
														<time>{new Date(event.timestamp * 1000).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}</time>
													</div>
												</div>
											{/each}
										</div>
									</details>
								{/if}

								{#if selectedTask.status === 'succeeded'}
									<section class="result-card">
										<div class="result-head">
											<div class="success-mark">✓</div>
											<div><span>完了しました</span><strong>{selectedTask.title}</strong></div>
										</div>
										{#if eventDetail(resultEvent)}<p>{eventDetail(resultEvent)}</p>{/if}
										<div class="result-facts">
											<div><span>変更ファイル</span><strong>{changedFiles.length}</strong></div>
											<div><span>所要時間</span><strong>{elapsedTime(selectedTask)}</strong></div>
											<div><span>コスト</span><strong>${selectedTask.actual_cost.toFixed(4)}</strong></div>
										</div>
										{#if changedFiles.length}
											<button class="view-work" on:click={() => { inspectorTab = 'changes'; showInspector = true; }}>
												変更内容を確認
												<svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6" /></svg>
											</button>
										{/if}
									</section>
								{/if}
							</div>
						</article>
					</div>
				{/if}
			</div>

			<div class="composer-area">
				<form class="composer" on:submit|preventDefault={submitTask}>
					<textarea
						bind:this={composer}
						bind:value={prompt}
						on:input={autoGrow}
						on:keydown={(event) => {
							if (event.key === 'Enter' && !event.shiftKey) {
								event.preventDefault();
								submitTask();
							}
						}}
						placeholder={selectedProject ? 'OpenMに実装を依頼する' : '先にリポジトリを接続してください'}
						disabled={!selectedProject || submitting}
						rows="1"
					></textarea>
					<div class="composer-tools">
						<div>
							<button type="button" class="tool-button" on:click={() => (showProjectModal = true)} aria-label="リポジトリ">
								<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
							</button>
							<select bind:value={taskModel} aria-label="モデル">
								<option value="claude-glm-code">GLM Code</option>
								<option value="claude-glm-main">GLM Main</option>
							</select>
						</div>
						<button class="send-button" disabled={!prompt.trim() || !selectedProject || submitting} aria-label="送信">
							{#if submitting}<span class="spinner"></span>{:else}<svg viewBox="0 0 24 24"><path d="m5 12 7-7 7 7M12 5v14" /></svg>{/if}
						</button>
					</div>
				</form>
				<p>OpenMは専用Sandboxでコードを変更します。重要な差分は確認してください。</p>
			</div>
		</main>

		{#if selectedTask}
			<aside class:open={showInspector} class="inspector">
				<div class="inspector-head">
					<div>
						<span>ARTIFACTS</span>
						<strong>Workspace</strong>
					</div>
					<button class="icon-button" on:click={() => (showInspector = false)} aria-label="閉じる">
						<svg viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18" /></svg>
					</button>
				</div>
				<div class="inspector-tabs">
					<button class:active={inspectorTab === 'changes'} on:click={() => (inspectorTab = 'changes')}>変更</button>
					<button class:active={inspectorTab === 'terminal'} on:click={() => (inspectorTab = 'terminal')}>実行</button>
					<button class:active={inspectorTab === 'context'} on:click={() => (inspectorTab = 'context')}>環境</button>
				</div>
				<div class="inspector-body">
					{#if inspectorTab === 'changes'}
						<div class="inspector-summary">
							<span>WORKTREE</span>
							<strong>{selectedTask.branch_name}</strong>
							<small>{selectedTask.worktree_path ?? '準備中'}</small>
						</div>
						{#if changedFiles.length}
							<div class="file-list">
								{#each changedFiles as file}<div><span>M</span><strong>{file}</strong></div>{/each}
							</div>
							{#if currentDiff}<pre class="diff">{currentDiff}</pre>{/if}
						{:else}
							<div class="inspector-empty"><span>◇</span><strong>変更はまだありません</strong><p>ファイルを編集すると、ここに差分が表示されます。</p></div>
						{/if}
					{:else if inspectorTab === 'terminal'}
						<div class="terminal">
							<div class="terminal-command">$ openm run {selectedTask.id.slice(0, 12)}</div>
							{#each terminalEvents as event}<pre>{eventDetail(event)}</pre>{/each}
							<span class="cursor"></span>
						</div>
					{:else}
						<dl class="context">
							<div><dt>Project</dt><dd>{selectedProject?.name}</dd></div>
							<div><dt>Model</dt><dd>{selectedTask.model}</dd></div>
							<div><dt>Branch</dt><dd>{selectedTask.branch_name}</dd></div>
							<div><dt>Isolation</dt><dd>User sandbox</dd></div>
							<div><dt>Max turns</dt><dd>{selectedTask.max_turns}</dd></div>
							<div><dt>Budget</dt><dd>${selectedTask.max_budget.toFixed(2)}</dd></div>
						</dl>
					{/if}
				</div>
			</aside>
		{/if}
	</div>
</div>

{#if showProjectModal}
	<button class="modal-backdrop" on:click={() => (showProjectModal = false)} aria-label="閉じる"></button>
	<form class="modal" on:submit|preventDefault={submitProject}>
		<div class="modal-kicker">NEW PROJECT</div>
		<h2>リポジトリを接続</h2>
		<p>ユーザー専用Sandboxへcloneし、OpenMが作業できるようにします。</p>
		<label><span>プロジェクト名</span><input bind:value={projectName} placeholder="openm-web" required /></label>
		<label><span>Repository URL</span><input bind:value={repositoryUrl} placeholder="https://github.com/org/repo.git" required /></label>
		<label><span>Default branch</span><input bind:value={defaultBranch} placeholder="main" required /></label>
		<div class="modal-actions">
			<button type="button" on:click={() => (showProjectModal = false)}>キャンセル</button>
			<button class="primary" disabled={submitting}>{submitting ? '接続中…' : '接続する'}</button>
		</div>
	</form>
{/if}

<style>
	:global(body) { overflow: hidden; }
	:global(.dark) .openm-chat { --bg: #0d0e0f; --panel: #141516; --raised: #1b1d1f; --line: #2a2c2f; --text: #f2f3ef; --muted: #989c96; --soft: #71756f; --bubble: #202225; --input: #1c1e20; }
	.openm-chat { --bg: #f7f7f5; --panel: #fff; --raised: #f2f3f0; --line: #e3e4df; --text: #20221f; --muted: #73776f; --soft: #989b95; --bubble: #e9eae6; --input: #fff; --accent: #9ee63b; --accent-strong: #669e18; height: 100dvh; background: var(--bg); color: var(--text); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
	button, select, textarea, input { font: inherit; }
	button { color: inherit; }
	svg { width: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
	.chat-header { height: 64px; display: flex; align-items: center; justify-content: space-between; padding: 0 18px; border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--panel) 92%, transparent); backdrop-filter: blur(16px); position: relative; z-index: 30; }
	.header-left, .header-actions, .header-center { display: flex; align-items: center; }
	.header-left { gap: 11px; min-width: 220px; }
	.agent-mark, .empty-mark, .openm-avatar { display: flex; align-items: end; gap: 3px; }
	.agent-mark { width: 32px; height: 32px; padding: 7px; border: 1px solid var(--line); border-radius: 9px; background: var(--panel); }
	.agent-mark span, .empty-mark span, .openm-avatar span { width: 4px; background: var(--accent); border-radius: 3px; }
	.agent-mark span:nth-child(1), .openm-avatar span:nth-child(1) { height: 8px; }
	.agent-mark span:nth-child(2), .openm-avatar span:nth-child(2) { height: 14px; }
	.agent-mark span:nth-child(3), .openm-avatar span:nth-child(3) { height: 11px; }
	.title-stack { display: flex; flex-direction: column; line-height: 1.15; }
	.title-stack strong { font-size: 15px; letter-spacing: -.02em; }
	.title-stack span { margin-top: 4px; font-size: 10px; color: var(--muted); }
	.header-center { gap: 7px; font-size: 11px; color: var(--muted); }
	.header-center i { width: 1px; height: 14px; margin: 0 5px; background: var(--line); }
	.presence { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent); flex: none; }
	.header-actions { justify-content: flex-end; gap: 8px; min-width: 220px; }
	.header-actions button, .icon-button { border: 1px solid var(--line); background: var(--panel); border-radius: 9px; height: 36px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
	.artifact-button, .new-button { gap: 7px; padding: 0 11px; font-size: 12px; font-weight: 600; }
	.new-button { background: var(--text) !important; color: var(--bg) !important; border-color: var(--text) !important; }
	.icon-button { width: 36px; padding: 0; }
	button:disabled { opacity: .4; cursor: not-allowed; }
	.app-body { display: flex; height: calc(100dvh - 64px); overflow: hidden; position: relative; }
	.thread-sidebar { width: 250px; flex: none; border-right: 1px solid var(--line); background: var(--panel); padding: 16px 12px 12px; display: flex; flex-direction: column; z-index: 22; }
	.project-switcher { display: grid; grid-template-columns: 1fr 32px; gap: 6px; position: relative; }
	.project-switcher label { grid-column: 1 / -1; font-size: 9px; letter-spacing: .13em; color: var(--soft); font-weight: 700; padding-left: 2px; }
	.select-wrap { position: relative; }
	.select-wrap select { width: 100%; height: 36px; border: 1px solid var(--line); border-radius: 8px; appearance: none; background: var(--bg); color: var(--text); padding: 0 28px 0 10px; font-size: 12px; font-weight: 600; }
	.select-wrap svg { width: 14px; position: absolute; right: 8px; top: 11px; pointer-events: none; }
	.connect-button { border: 1px solid var(--line); border-radius: 8px; background: var(--bg); font-size: 20px; cursor: pointer; }
	.sidebar-new { margin: 12px 0 18px; height: 39px; border: 0; border-radius: 9px; background: var(--text); color: var(--bg); display: flex; align-items: center; justify-content: center; gap: 7px; font-size: 12px; font-weight: 700; cursor: pointer; }
	.sidebar-new svg { width: 16px; }
	.thread-label { display: flex; justify-content: space-between; padding: 0 4px 8px; color: var(--soft); font-size: 9px; letter-spacing: .12em; }
	.thread-label b { letter-spacing: 0; }
	.thread-list { overflow-y: auto; flex: 1; }
	.thread { width: 100%; display: flex; gap: 9px; align-items: flex-start; padding: 10px 9px; border: 0; background: transparent; border-radius: 9px; text-align: left; cursor: pointer; }
	.thread:hover { background: var(--raised); }
	.thread.active { background: var(--bubble); }
	.thread-status { width: 7px; height: 7px; margin-top: 5px; border-radius: 50%; background: var(--soft); flex: none; }
	.thread-status.status-running, .thread-status.status-preparing, .thread-status.status-queued { background: var(--accent); }
	.thread-status.status-waiting_permission { background: #f3ab3b; }
	.thread-status.status-failed { background: #ef665f; }
	.thread-copy { min-width: 0; display: flex; flex-direction: column; }
	.thread-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 600; }
	.thread-copy small { margin-top: 4px; color: var(--muted); font-size: 10px; }
	.no-threads { padding: 16px 8px; color: var(--muted); font-size: 11px; line-height: 1.6; }
	.skeleton { height: 44px; margin: 5px; border-radius: 8px; background: var(--raised); animation: pulse 1.5s infinite; }
	.skeleton.short { width: 72%; }
	.sandbox-note { border-top: 1px solid var(--line); padding: 13px 5px 2px; display: flex; align-items: center; gap: 9px; }
	.sandbox-note div { display: flex; flex-direction: column; font-size: 10px; }
	.sandbox-note small { margin-top: 2px; color: var(--muted); }
	.conversation { min-width: 0; flex: 1; display: flex; flex-direction: column; background: var(--bg); position: relative; transition: margin .2s ease; }
	.messages { flex: 1; overflow-y: auto; scrollbar-width: thin; }
	.conversation-inner { max-width: 820px; margin: 0 auto; padding: 48px 28px 160px; }
	.task-meta { display: flex; gap: 8px; color: var(--soft); font-size: 10px; margin: 0 0 28px 54px; }
	.task-meta i { font-style: normal; }
	.user-message, .agent-message { display: grid; grid-template-columns: 36px 1fr; gap: 16px; }
	.user-message { margin-bottom: 42px; }
	.user-avatar, .openm-avatar { width: 34px; height: 34px; border-radius: 10px; }
	.user-avatar { display: grid; place-items: center; background: var(--bubble); font-size: 8px; font-weight: 800; color: var(--muted); }
	.openm-avatar { box-sizing: border-box; align-items: end; justify-content: center; padding: 8px; background: var(--text); }
	.message-author { height: 28px; display: flex; align-items: center; gap: 9px; }
	.message-author strong { font-size: 13px; }
	.message-author time, .model-name { color: var(--muted); font-size: 10px; }
	.user-message p { margin: 5px 0 0; white-space: pre-wrap; font-size: 15px; line-height: 1.7; }
	.agent-content { min-width: 0; }
	.run-card, .activity-card, .result-card, .approval-card { margin-top: 9px; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); overflow: hidden; }
	.run-card { padding: 18px 18px 14px; position: relative; }
	.run-card.attention { border-color: #d9a74c; }
	.run-card-head { display: flex; justify-content: space-between; gap: 15px; }
	.run-status { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 10px; font-weight: 700; }
	.run-status i { width: 7px; height: 7px; background: var(--accent); border-radius: 50%; }
	.run-status.status-failed i, .run-status.status-cancelled i { background: #ef665f; }
	.run-status.status-waiting_permission i { background: #f3ab3b; }
	.run-copy h2 { margin: 8px 0 4px; font-size: 15px; line-height: 1.35; }
	.run-copy p { margin: 0; color: var(--muted); font-size: 10px; }
	.progress-number { font-size: 31px; font-weight: 500; letter-spacing: -.06em; }
	.progress-number small { font-size: 11px; color: var(--muted); margin-left: 2px; }
	.progress-track { height: 3px; margin-top: 17px; background: var(--raised); border-radius: 3px; overflow: hidden; }
	.progress-track span { display: block; height: 100%; background: var(--accent); transition: width .4s ease; }
	.phase-list { display: grid; grid-template-columns: repeat(6, 1fr); margin-top: 11px; }
	.phase { display: flex; align-items: center; gap: 4px; color: var(--soft); }
	.phase span { width: 13px; height: 13px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: 50%; font-size: 8px; }
	.phase small { font-size: 8px; }
	.phase-complete { color: var(--accent-strong); }
	.phase-complete span { background: var(--accent); border-color: var(--accent); color: #182006; }
	.phase-active { color: var(--text); font-weight: 700; }
	.phase-active span { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent); }
	.phase-attention { color: #c48a29; }
	.phase-failed { color: #d84d47; }
	.text-action { border: 0; background: transparent; color: var(--accent-strong); padding: 12px 0 0; font-size: 10px; cursor: pointer; }
	.text-action.danger { color: #d84d47; }
	.activity-card summary { list-style: none; padding: 14px 16px; display: flex; align-items: center; gap: 10px; cursor: pointer; }
	.activity-card summary::-webkit-details-marker { display: none; }
	.activity-symbol { width: 25px; height: 25px; display: grid; place-items: center; border-radius: 7px; background: var(--raised); color: var(--accent-strong); }
	.activity-card summary div { display: flex; flex: 1; flex-direction: column; }
	.activity-card summary strong { font-size: 11px; }
	.activity-card summary small { margin-top: 2px; color: var(--muted); font-size: 9px; }
	.activity-card summary svg { width: 15px; transition: transform .2s; }
	.activity-card[open] summary svg { transform: rotate(180deg); }
	.activity-list { border-top: 1px solid var(--line); padding: 8px 16px 12px; max-height: 330px; overflow-y: auto; }
	.activity-row { display: grid; grid-template-columns: 14px 1fr; gap: 8px; min-height: 42px; }
	.activity-line { position: relative; border-left: 1px solid var(--line); margin-left: 4px; }
	.activity-line span { position: absolute; left: -4px; top: 8px; width: 7px; height: 7px; border-radius: 50%; background: var(--soft); }
	.activity-line span.live { background: var(--accent); }
	.activity-row > div:last-child { padding: 5px 0 10px; min-width: 0; position: relative; }
	.activity-row strong { font-size: 10px; font-weight: 600; }
	.activity-row time { position: absolute; right: 0; top: 7px; color: var(--soft); font-size: 8px; }
	.activity-row pre { margin: 5px 50px 0 0; color: var(--muted); font: 9px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 80px; overflow: hidden; }
	.approval-card { padding: 16px; display: grid; grid-template-columns: 32px 1fr; gap: 12px; border-color: #d9a74c; }
	.approval-icon { width: 30px; height: 30px; border-radius: 9px; background: #f3ab3b; color: #281900; display: grid; place-items: center; font-weight: 900; }
	.approval-card span { font-size: 9px; color: #c48a29; font-weight: 700; }
	.approval-card h3 { margin: 4px 0 9px; font-size: 13px; }
	.approval-card pre { margin: 0; padding: 9px; border-radius: 7px; background: var(--raised); font: 9px/1.5 ui-monospace, monospace; max-height: 110px; overflow: auto; }
	.approval-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 11px; }
	.approval-actions button { padding: 7px 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); font-size: 9px; font-weight: 700; cursor: pointer; }
	.approval-actions .primary { background: var(--text); color: var(--bg); }
	.result-card { padding: 16px; }
	.result-head { display: flex; gap: 10px; align-items: center; }
	.success-mark { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: var(--accent); color: #182006; font-weight: 800; }
	.result-head div:last-child { display: flex; flex-direction: column; }
	.result-head span { color: var(--accent-strong); font-size: 9px; font-weight: 700; }
	.result-head strong { margin-top: 3px; font-size: 13px; }
	.result-card > p { margin: 13px 0; font-size: 11px; line-height: 1.6; color: var(--muted); white-space: pre-wrap; }
	.result-facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
	.result-facts div { background: var(--bg); padding: 10px; display: flex; flex-direction: column; }
	.result-facts span { color: var(--muted); font-size: 8px; }
	.result-facts strong { margin-top: 4px; font-size: 11px; }
	.view-work { width: 100%; height: 36px; margin-top: 11px; border: 0; border-radius: 8px; background: var(--text); color: var(--bg); display: flex; align-items: center; justify-content: center; gap: 7px; font-size: 10px; font-weight: 700; cursor: pointer; }
	.view-work svg { width: 14px; }
	.empty-chat { min-height: calc(100dvh - 210px); display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 35px 24px; text-align: center; }
	.empty-mark { height: 49px; align-items: end; gap: 6px; margin-bottom: 23px; }
	.empty-mark span { width: 8px; }
	.empty-mark span:nth-child(1) { height: 25px; }.empty-mark span:nth-child(2) { height: 47px; }.empty-mark span:nth-child(3) { height: 34px; }
	.empty-chat h1 { margin: 0; font-size: clamp(28px, 4vw, 42px); letter-spacing: -.055em; font-weight: 650; }
	.empty-chat p { margin: 15px 0 27px; color: var(--muted); font-size: 12px; line-height: 1.7; }
	.suggestions { width: min(100%, 530px); display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
	.suggestions button { min-height: 68px; padding: 11px; border: 1px solid var(--line); border-radius: 11px; background: var(--panel); text-align: left; font-size: 10px; cursor: pointer; }
	.suggestions button:hover { border-color: var(--soft); transform: translateY(-1px); }
	.suggestions span { display: block; color: var(--accent-strong); font: 9px ui-monospace, monospace; margin-bottom: 9px; }
	.composer-area { position: absolute; z-index: 10; bottom: 0; left: 0; right: 0; padding: 30px 24px 10px; background: linear-gradient(transparent, var(--bg) 35%); }
	.composer { max-width: 760px; margin: 0 auto; padding: 11px 12px 9px; border: 1px solid var(--line); border-radius: 17px; background: var(--input); box-shadow: 0 10px 35px rgba(0,0,0,.08); }
	.composer:focus-within { border-color: color-mix(in srgb, var(--soft) 70%, var(--line)); }
	.composer textarea { display: block; width: 100%; min-height: 27px; max-height: 180px; resize: none; box-sizing: border-box; padding: 4px 5px 8px; border: 0; outline: 0; background: transparent; color: var(--text); font-size: 14px; line-height: 1.5; }
	.composer textarea::placeholder { color: var(--soft); }
	.composer-tools, .composer-tools > div { display: flex; align-items: center; justify-content: space-between; }
	.composer-tools > div { gap: 5px; }
	.tool-button { width: 29px; height: 29px; border: 1px solid var(--line); border-radius: 8px; background: transparent; display: grid; place-items: center; cursor: pointer; }
	.tool-button svg { width: 15px; }
	.composer select { height: 29px; padding: 0 7px; border: 0; border-radius: 7px; background: var(--raised); color: var(--muted); font-size: 9px; outline: 0; }
	.send-button { width: 31px; height: 31px; border: 0; border-radius: 9px; background: var(--text); color: var(--bg); display: grid; place-items: center; cursor: pointer; }
	.send-button svg { width: 17px; }
	.composer-area > p { margin: 6px auto 0; text-align: center; color: var(--soft); font-size: 8px; }
	.spinner { width: 12px; height: 12px; border: 2px solid color-mix(in srgb, var(--bg) 35%, transparent); border-top-color: var(--bg); border-radius: 50%; animation: spin .7s linear infinite; }
	.inspector { width: 0; flex: none; overflow: hidden; background: var(--panel); border-left: 0 solid var(--line); transition: width .22s ease; z-index: 21; }
	.inspector.open { width: min(390px, 34vw); border-left-width: 1px; }
	.inspector-head { height: 62px; padding: 0 15px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); }
	.inspector-head > div { display: flex; flex-direction: column; }
	.inspector-head span { color: var(--soft); font-size: 8px; letter-spacing: .13em; }
	.inspector-head strong { margin-top: 4px; font-size: 13px; }
	.inspector-tabs { display: grid; grid-template-columns: repeat(3,1fr); padding: 10px 12px 0; border-bottom: 1px solid var(--line); }
	.inspector-tabs button { padding: 9px 0; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); font-size: 9px; cursor: pointer; }
	.inspector-tabs button.active { color: var(--text); border-bottom-color: var(--accent); }
	.inspector-body { height: calc(100% - 112px); overflow: auto; padding: 16px; }
	.inspector-summary { display: flex; flex-direction: column; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
	.inspector-summary span { color: var(--soft); font-size: 8px; letter-spacing: .1em; }
	.inspector-summary strong { margin-top: 7px; font-size: 11px; overflow-wrap: anywhere; }
	.inspector-summary small { margin-top: 5px; color: var(--muted); font: 8px/1.4 ui-monospace, monospace; overflow-wrap: anywhere; }
	.file-list { padding: 10px 0; }
	.file-list div { padding: 8px 3px; display: flex; gap: 8px; border-bottom: 1px solid var(--line); font-size: 9px; overflow-wrap: anywhere; }
	.file-list span { color: var(--accent-strong); font-family: ui-monospace, monospace; }
	.diff, .terminal { margin: 10px 0 0; padding: 12px; border-radius: 9px; background: #0c0e0d; color: #b9c1b5; font: 9px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; overflow: auto; }
	.diff { max-height: 55vh; }
	.terminal { min-height: 260px; }
	.terminal pre { margin: 10px 0; color: inherit; white-space: pre-wrap; }
	.terminal-command { color: var(--accent); }
	.cursor { display: inline-block; width: 6px; height: 11px; background: var(--accent); animation: pulse 1s infinite; }
	.context { margin: 0; }
	.context div { display: grid; grid-template-columns: 88px 1fr; gap: 8px; padding: 11px 0; border-bottom: 1px solid var(--line); font-size: 10px; }
	.context dt { color: var(--muted); }
	.context dd { margin: 0; overflow-wrap: anywhere; }
	.inspector-empty { min-height: 260px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: var(--muted); }
	.inspector-empty > span { font-size: 28px; color: var(--soft); }
	.inspector-empty strong { margin-top: 12px; color: var(--text); font-size: 11px; }
	.inspector-empty p { max-width: 190px; font-size: 9px; line-height: 1.6; }
	.modal-backdrop, .mobile-scrim { position: fixed; inset: 0; border: 0; background: rgba(0,0,0,.55); z-index: 80; }
	.modal { width: min(430px, calc(100vw - 32px)); box-sizing: border-box; position: fixed; z-index: 81; left: 50%; top: 50%; transform: translate(-50%,-50%); padding: 24px; border: 1px solid var(--line); border-radius: 17px; background: var(--panel); color: var(--text); box-shadow: 0 24px 80px rgba(0,0,0,.25); }
	.modal-kicker { color: var(--accent-strong); font-size: 9px; letter-spacing: .14em; font-weight: 800; }
	.modal h2 { margin: 8px 0; font-size: 22px; letter-spacing: -.03em; }
	.modal > p { margin: 0 0 20px; color: var(--muted); font-size: 11px; line-height: 1.6; }
	.modal label { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; }
	.modal label span { color: var(--muted); font-size: 9px; font-weight: 700; }
	.modal input { height: 40px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 9px; background: var(--bg); color: var(--text); padding: 0 11px; outline: 0; font-size: 12px; }
	.modal input:focus { border-color: var(--accent-strong); }
	.modal-actions { margin-top: 20px; display: flex; justify-content: flex-end; gap: 7px; }
	.modal-actions button { padding: 9px 13px; border: 1px solid var(--line); border-radius: 8px; background: transparent; font-size: 10px; cursor: pointer; }
	.modal-actions .primary { background: var(--text); color: var(--bg); border-color: var(--text); }
	.mobile-only, .mobile-scrim { display: none; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@keyframes pulse { 50% { opacity: .45; } }

	@media (max-width: 960px) {
		.header-center { display: none; }
		.inspector { position: absolute; right: 0; top: 0; bottom: 0; box-shadow: -18px 0 40px rgba(0,0,0,.15); }
		.inspector.open { width: min(420px, 78vw); }
	}
	@media (max-width: 720px) {
		.chat-header { height: 56px; padding: 0 10px; }
		.app-body { height: calc(100dvh - 56px); }
		.header-left, .header-actions { min-width: 0; }
		.mobile-only { display: inline-flex; }
		.title-stack span, .artifact-button span, .new-button span { display: none; }
		.agent-mark { display: none; }
		.header-actions button { width: 36px; padding: 0; }
		.thread-sidebar { position: absolute; left: 0; top: 0; bottom: 0; width: min(290px, 86vw); transform: translateX(-102%); transition: transform .2s ease; box-shadow: 16px 0 45px rgba(0,0,0,.2); }
		.thread-sidebar.open { transform: translateX(0); }
		.mobile-scrim { display: block; position: absolute; z-index: 20; }
		.conversation-inner { padding: 28px 16px 150px; }
		.task-meta { margin: 0 0 21px; }
		.user-message, .agent-message { grid-template-columns: 30px 1fr; gap: 10px; }
		.user-avatar, .openm-avatar { width: 29px; height: 29px; border-radius: 8px; }
		.openm-avatar { padding: 7px; }
		.user-message { margin-bottom: 30px; }
		.user-message p { font-size: 14px; }
		.run-card { padding: 14px 13px 12px; }
		.progress-number { font-size: 25px; }
		.phase-list { grid-template-columns: repeat(3, 1fr); gap: 8px 4px; }
		.phase small { font-size: 7px; }
		.activity-card summary { padding: 12px; }
		.activity-list { padding-left: 12px; padding-right: 12px; }
		.result-facts { grid-template-columns: 1fr; }
		.result-facts div { flex-direction: row; align-items: center; justify-content: space-between; }
		.composer-area { padding: 24px 10px 7px; }
		.composer { border-radius: 15px; }
		.composer-area > p { display: none; }
		.empty-chat { min-height: calc(100dvh - 175px); padding: 25px 18px; }
		.empty-chat p br { display: none; }
		.suggestions { grid-template-columns: 1fr; max-width: 330px; }
		.suggestions button { min-height: 48px; }
		.suggestions span { display: inline; margin-right: 8px; }
		.inspector { position: absolute; left: 0; width: 100%; transform: translateY(102%); top: 16%; border: 1px solid var(--line); border-radius: 18px 18px 0 0; transition: transform .22s ease; box-shadow: 0 -18px 50px rgba(0,0,0,.25); }
		.inspector.open { width: 100%; transform: translateY(0); }
	}
</style>
