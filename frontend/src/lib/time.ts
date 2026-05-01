// ISO timestamp helpers shared by mocks. The base time is fixed so
// snapshot tests stay reproducible; in production these are replaced
// by server timestamps via TanStack Query.

export const MOCK_NOW = new Date('2026-04-26T05:23:00Z');

export const isoMinusMin = (m: number): string =>
  new Date(MOCK_NOW.getTime() - m * 60_000).toISOString();

export const isoMinusHour = (h: number): string =>
  new Date(MOCK_NOW.getTime() - h * 3_600_000).toISOString();

export const isoMinusDay = (d: number): string =>
  new Date(MOCK_NOW.getTime() - d * 86_400_000).toISOString();
