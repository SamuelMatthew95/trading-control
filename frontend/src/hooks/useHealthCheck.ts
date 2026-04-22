import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { HealthResponse, BotControlResponse } from "@/types/health";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export const useHealthCheck = () => {
  return useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: async () => {
      const response = await axios.get(`${API_BASE}/api/health`);
      return response.data;
    },
    refetchInterval: 3000, // 3-second polling
    staleTime: 1000,
    retry: 3,
    retryDelay: 1000,
  });
};

export const useBotControl = () => {
  const queryClient = useQueryClient();

  const startBot = useMutation<BotControlResponse, Error>({
    mutationFn: async () => {
      const response = await axios.post(`${API_BASE}/api/bot/start`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
  });

  const stopBot = useMutation<BotControlResponse, Error>({
    mutationFn: async () => {
      const response = await axios.post(`${API_BASE}/api/bot/stop`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
  });

  return {
    startBot,
    stopBot,
  };
};
