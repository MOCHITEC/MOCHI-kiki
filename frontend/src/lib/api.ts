import type {
  ApiErrorBody,
  AuthMeResponse,
  CreateBotRequest,
  CreateBotResponse,
  Meeting,
  MeetingListResponse,
  MinutesResponse,
  TimelineResponse,
  UtteranceListResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const LOGIN_PATH = "/api/console/auth/login";

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text };
    }
  }

  if (!res.ok) {
    const err = body as ApiErrorBody | null;
    const code = err?.error?.code ?? "unknown_error";
    const message = err?.error?.message ?? res.statusText;
    if (
      res.status === 401 &&
      path !== LOGIN_PATH &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/login"
    ) {
      const next = window.location.pathname + window.location.search;
      window.location.replace(
        `/login?next=${encodeURIComponent(next)}`,
      );
    }
    throw new ApiError(res.status, code, message);
  }

  return (body as T) ?? (undefined as T);
}

export const api = {
  login(username: string, password: string): Promise<void> {
    return request<void>("/api/console/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  },
  logout(): Promise<void> {
    return request<void>("/api/console/auth/logout", { method: "POST" });
  },
  me(): Promise<AuthMeResponse> {
    return request<AuthMeResponse>("/api/console/auth/me");
  },

  createBot(payload: CreateBotRequest): Promise<CreateBotResponse> {
    return request<CreateBotResponse>("/api/console/bots", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  leaveBot(botId: string): Promise<void> {
    return request<void>(
      `/api/console/bots/${encodeURIComponent(botId)}/leave`,
      { method: "POST" },
    );
  },

  listMeetings(params: {
    limit?: number;
    before?: string;
  } = {}): Promise<MeetingListResponse> {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.before) qs.set("before", params.before);
    const q = qs.toString();
    return request<MeetingListResponse>(
      `/api/console/meetings${q ? `?${q}` : ""}`,
    );
  },
  getMeeting(meetingId: string): Promise<Meeting> {
    return request<Meeting>(
      `/api/console/meetings/${encodeURIComponent(meetingId)}`,
    );
  },
  listUtterances(
    meetingId: string,
    params: { since?: string; limit?: number } = {},
  ): Promise<UtteranceListResponse> {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.limit) qs.set("limit", String(params.limit));
    const q = qs.toString();
    return request<UtteranceListResponse>(
      `/api/console/meetings/${encodeURIComponent(meetingId)}/utterances${q ? `?${q}` : ""}`,
    );
  },
  transcriptUrl(meetingId: string): string {
    return `/api/console/meetings/${encodeURIComponent(meetingId)}/transcript.txt`;
  },
  getMinutes(meetingId: string): Promise<MinutesResponse> {
    return request<MinutesResponse>(
      `/api/console/meetings/${encodeURIComponent(meetingId)}/minutes`,
    );
  },
  getTimeline(meetingId: string): Promise<TimelineResponse> {
    return request<TimelineResponse>(
      `/api/console/meetings/${encodeURIComponent(meetingId)}/timeline`,
    );
  },
};
