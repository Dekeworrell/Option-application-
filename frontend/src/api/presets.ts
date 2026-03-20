import axios from "axios";
import { api } from "./client";

export type Preset = {
  id: number;
  name: string;
  option_type: "call" | "put";
  delta_target: number;
  min_premium?: number | null;
  min_return_pct?: number | null;
  use_rsi_filter: boolean;
  rsi_max?: number | null;
  use_ma30_filter: boolean;
};

export async function getPresets() {
  const { data } = await api.get("/presets");
  return data;
}

export async function createPreset(payload: any) {
  try {
    const { data } = await api.post("/presets", payload);
    return data;
  } catch (err) {
    if (axios.isAxiosError(err)) {
      const detail =
        err.response?.data?.detail ??
        err.response?.data ??
        err.message;

      throw new Error(
        typeof detail === "string" ? detail : JSON.stringify(detail)
      );
    }

    throw err;
  }
}

export async function deletePreset(id: number) {
  await api.delete(`/presets/${id}`);
}

export async function setDefaultPreset(listId: number, presetId: number) {
  const { data } = await api.put(`/lists/${listId}/default-preset/${presetId}`);
  return data;
}

export async function getDefaultPreset(listId: number) {
  const { data } = await api.get(`/lists/${listId}/default-preset`);
  return data;
}
