"use client";

import { type ReactNode, createContext, useContext } from "react";

/** Where a notebook's documents and answers live: on this computer (the desktop window, the default) or
 * in the person's account on a service (the web app). The screens say which, so what they promise about
 * privacy is true where they run. */
export type NotebookPlace = "device" | "hosted";

const Place = createContext<NotebookPlace>("device");

export function NotebookPlaceProvider({
  place,
  children,
}: {
  place: NotebookPlace;
  children: ReactNode;
}) {
  return <Place.Provider value={place}>{children}</Place.Provider>;
}

export function useNotebookPlace(): NotebookPlace {
  return useContext(Place);
}
