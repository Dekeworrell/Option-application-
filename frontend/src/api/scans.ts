import { api } from "./client";

export type RunScanResponse = {
  status?: string;
  message?: string;
  [key: string]: any;
};

export async function runScan(listId: number): Promise<RunScanResponse> {
  const { data } = await api.post(`/lists/${listId}/scan/run`, {});
  return data;
}

export async function getLatestScanResults(listId: number) {
  const { data } = await api.get(`/lists/${listId}/scan-results/latest`);
  return data;
}

export async function getScanHistory(listId: number) {
  const { data } = await api.get(`/lists/${listId}/scan-results/history`);
  return data;
}
