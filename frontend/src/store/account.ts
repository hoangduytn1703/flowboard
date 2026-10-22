import { create } from "zustand";
import type { AccountMe } from "../api/account";

interface AccountStore {
  me: AccountMe | null;
  setMe(me: AccountMe | null): void;
}

/** Who is logged in to Flowboard (null = not logged in / unknown). */
export const useAccountStore = create<AccountStore>((set) => ({
  me: null,
  setMe: (me) => set({ me }),
}));
