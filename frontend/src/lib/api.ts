import axios from "axios";
import type {
  AgentDetail,
  LeaderboardEntry,
  MarketSnapshot,
  PopulationSummary,
  SystemHealth,
} from "../types/api";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const client = axios.create({ baseURL });

export const api = {
  health: () => client.get<SystemHealth>("/api/system/health").then((r) => r.data),
  market: () => client.get<MarketSnapshot>("/api/market").then((r) => r.data),
  population: () => client.get<PopulationSummary>("/api/population").then((r) => r.data),
  leaderboard: (limit = 50) =>
    client.get<LeaderboardEntry[]>("/api/leaderboard", { params: { limit } }).then((r) => r.data),
  agent: (id: string) => client.get<AgentDetail>(`/api/agents/${id}`).then((r) => r.data),
};
