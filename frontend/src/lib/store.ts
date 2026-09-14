import { create } from "zustand";
type State = {
  page: string;
  parcel: string | null;
  selected: string | null;
  floor: string | null;
  mode: "3D" | "2D";
  exploded: boolean;
  slice: boolean;
  slicePosition: number;
  performance: "Standard" | "Low-end";
  issue: string | null;
  reset: number;
  notice: string;
  appearance: boolean;
  zoom: number;
  set: (v: Partial<Omit<State, "set">>) => void;
};
export const useWorkspace = create<State>((set) => ({
  page: "Home",
  parcel: null,
  selected: null,
  floor: null,
  mode: "3D",
  exploded: false,
  slice: false,
  slicePosition: 0,
  performance: "Standard",
  issue: null,
  reset: 0,
  notice: "",
  appearance: true,
  zoom: 0,
  set: (v) => set(v),
}));
