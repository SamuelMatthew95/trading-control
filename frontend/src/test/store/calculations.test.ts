/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect } from "vitest";

const calculateDailyPnl = (orders: any[]): number => {
  if (!orders || orders.length === 0) return 0;
  return orders
    .filter(
      (o) => o && typeof o.pnl === "number" && isFinite(o.pnl) && !isNaN(o.pnl),
    )
    .reduce((sum, o) => sum + o.pnl, 0);
};

const calculateWinRate = (orders: any[]): number => {
  const valid = orders.filter(
    (o) => o && typeof o.pnl === "number" && !isNaN(o.pnl),
  );
  if (valid.length === 0) return 0;
  return (valid.filter((o) => o.pnl > 0).length / valid.length) * 100;
};

const calculateBestWorstDay = (orders: any[]) => {
  const dailyMap = new Map<string, number>();
  orders.forEach((order) => {
    if (
      order?.timestamp &&
      typeof order.pnl === "number" &&
      isFinite(order.pnl)
    ) {
      const date = new Date(order.timestamp).toDateString();
      dailyMap.set(date, (dailyMap.get(date) || 0) + order.pnl);
    }
  });
  const values = Array.from(dailyMap.values());
  return {
    bestDay: values.length > 0 ? Math.max(...values) : 0,
    worstDay: values.length > 0 ? Math.min(...values) : 0,
  };
};

describe("calculateDailyPnl", () => {
  it("returns 0 for empty orders", () => expect(calculateDailyPnl([])).toBe(0));
  it("returns 0 for null input", () =>
    expect(calculateDailyPnl(null as any)).toBe(0));
  it("sums valid P&L values", () =>
    expect(calculateDailyPnl([{ pnl: 100 }, { pnl: 200 }])).toBe(300));
  it("ignores NaN pnl values", () =>
    expect(calculateDailyPnl([{ pnl: 100 }, { pnl: NaN }])).toBe(100));
  it("ignores null pnl values", () =>
    expect(calculateDailyPnl([{ pnl: 100 }, { pnl: null }])).toBe(100));
  it("ignores undefined orders", () =>
    expect(calculateDailyPnl([{ pnl: 100 }, null, undefined] as any)).toBe(
      100,
    ));
  it("handles negative P&L", () =>
    expect(calculateDailyPnl([{ pnl: 100 }, { pnl: -50 }])).toBe(50));
  it("handles all losing trades", () =>
    expect(calculateDailyPnl([{ pnl: -100 }, { pnl: -200 }])).toBe(-300));
});

describe("calculateWinRate", () => {
  it("returns 0 for empty orders", () => expect(calculateWinRate([])).toBe(0));
  it("returns 100 for all winning trades", () =>
    expect(calculateWinRate([{ pnl: 100 }, { pnl: 200 }])).toBe(100));
  it("returns 0 for all losing trades", () =>
    expect(calculateWinRate([{ pnl: -100 }, { pnl: -200 }])).toBe(0));
  it("returns 50 for equal wins and losses", () =>
    expect(calculateWinRate([{ pnl: 100 }, { pnl: -100 }])).toBe(50));
  it("ignores NaN pnl", () =>
    expect(calculateWinRate([{ pnl: 100 }, { pnl: NaN }])).toBe(100));
});

describe("calculateBestWorstDay", () => {
  const day1 = new Date("2024-01-01").toISOString();
  const day2 = new Date("2024-01-02").toISOString();

  it("returns 0s for empty orders", () => {
    expect(calculateBestWorstDay([])).toEqual({ bestDay: 0, worstDay: 0 });
  });

  it("calculates best and worst day correctly", () => {
    const orders = [
      { timestamp: day1, pnl: 500 },
      { timestamp: day1, pnl: 200 },
      { timestamp: day2, pnl: -300 },
    ];
    const result = calculateBestWorstDay(orders);
    expect(result.bestDay).toBe(700);
    expect(result.worstDay).toBe(-300);
  });

  it("ignores orders with invalid timestamps", () => {
    const orders = [
      { timestamp: null, pnl: 999 },
      { timestamp: day1, pnl: 100 },
    ];
    const result = calculateBestWorstDay(orders);
    expect(result.bestDay).toBe(100);
  });
});
