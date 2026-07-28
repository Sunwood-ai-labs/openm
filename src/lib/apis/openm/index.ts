import { WEBUI_API_BASE_URL } from '$lib/constants';

export type OpenMProject = {
	id: string;
	name: string;
	repository_url: string;
	default_branch: string;
	settings_json: Record<string, unknown>;
	created_at: number;
	updated_at: number;
};

export type OpenMTask = {
	id: string;
	project_id: string;
	parent_task_id: string | null;
	title: string;
	prompt: string;
	status: string;
	branch_name: string;
	worktree_path: string | null;
	agent_session_id: string | null;
	model: string;
	max_turns: number;
	max_budget: number;
	actual_cost: number;
	started_at: number | null;
	completed_at: number | null;
	created_at: number;
	updated_at: number;
};

export type OpenMEvent = {
	id: string;
	task_id: string;
	sequence: number;
	timestamp: number;
	type: string;
	data: Record<string, unknown>;
};

export type OpenMPermission = {
	id: string;
	task_id: string;
	tool_use_id: string;
	tool_name: string;
	tool_input_json: Record<string, unknown>;
	risk_level: string;
	status: string;
	decision: string | null;
	created_at: number;
};

export type OpenMDashboard = {
	projects: number;
	tasks: number;
	running: number;
	waiting_permission: number;
	completed: number;
	failed: number;
	sandbox: {
		status: string;
		isolation: string;
		active_tasks: number;
	};
	recent_projects: OpenMProject[];
	recent_tasks: OpenMTask[];
};

const request = async <T>(token: string, path: string, options: RequestInit = {}): Promise<T> => {
	const response = await fetch(`${WEBUI_API_BASE_URL}/openm${path}`, {
		...options,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`,
			...options.headers
		}
	});

	if (!response.ok) {
		const body = await response.json().catch(() => ({ detail: response.statusText }));
		throw new Error(body.detail ?? 'OpenM request failed');
	}

	if (response.status === 204) {
		return undefined as T;
	}
	return response.json();
};

export const getOpenMDashboard = (token: string) => request<OpenMDashboard>(token, '/dashboard');

export const getOpenMProjects = (token: string) => request<OpenMProject[]>(token, '/projects');

export const createOpenMProject = (
	token: string,
	project: {
		name: string;
		repository_url: string;
		default_branch: string;
	}
) =>
	request<OpenMProject>(token, '/projects', {
		method: 'POST',
		body: JSON.stringify(project)
	});

export const getOpenMTasks = (token: string, projectId?: string) =>
	request<OpenMTask[]>(
		token,
		`/tasks${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`
	);

export const createOpenMTask = (
	token: string,
	task: {
		project_id: string;
		title: string;
		prompt: string;
		model: string;
		max_turns?: number;
		max_budget?: number;
	}
) =>
	request<OpenMTask>(token, '/tasks', {
		method: 'POST',
		body: JSON.stringify(task)
	});

export const cancelOpenMTask = (token: string, taskId: string) =>
	request<OpenMTask>(token, `/tasks/${taskId}/cancel`, { method: 'POST' });

export const resumeOpenMTask = (token: string, taskId: string) =>
	request<OpenMTask>(token, `/tasks/${taskId}/resume`, { method: 'POST' });

export const getOpenMEvents = (token: string, taskId: string, after = 0) =>
	request<OpenMEvent[]>(token, `/tasks/${taskId}/events?after=${after}`);

export const getOpenMPermissions = (token: string, taskId: string) =>
	request<OpenMPermission[]>(token, `/tasks/${taskId}/permissions`);

export const decideOpenMPermission = (
	token: string,
	taskId: string,
	requestId: string,
	decision: 'allow_once' | 'allow_for_task' | 'deny'
) =>
	request<OpenMPermission>(token, `/tasks/${taskId}/permissions/${requestId}`, {
		method: 'POST',
		body: JSON.stringify({ decision })
	});
