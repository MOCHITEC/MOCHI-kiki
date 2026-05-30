export type LanguageCode = "ja" | "en";

export interface Meeting {
  meeting_id: string;
  bot_name: string | null;
  meeting_url: string | null;
  recall_bot_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  utterance_count: number;
}

export interface MeetingListResponse {
  meetings: Meeting[];
  next_cursor: string | null;
}

export interface Utterance {
  utterance_id?: string;
  speaker: string;
  text: string;
  timestamp: string;
  is_final?: boolean;
}

export interface UtteranceListResponse {
  utterances: Utterance[];
}

export interface CreateBotRequest {
  meeting_url: string;
  bot_name?: string;
  language_code?: LanguageCode;
}

export interface CreateBotResponse {
  meeting_id: string;
  bot_id: string;
}

export interface AuthMeResponse {
  username: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}
