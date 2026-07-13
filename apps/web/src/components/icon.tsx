type IconName = "activity" | "book" | "chevron" | "clock" | "document" | "home" | "lock" | "menu" | "search" | "shield" | "spark" | "warning";

const iconPaths: Record<IconName, readonly string[]> = {
  activity: ["M3 12h4l3-8 4 16 3-8h4"],
  book: ["M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5v-16Z", "M4 19a2 2 0 0 1 2-2h14"],
  chevron: ["m9 18 6-6-6-6"],
  clock: ["M12 7v5l3 2", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"],
  document: ["M7 3h7l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z", "M14 3v5h5", "M8 13h8", "M8 17h6"],
  home: ["m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V10Z", "M9 21v-7h6v7"],
  lock: ["M7 11V8a5 5 0 0 1 10 0v3", "M5 11h14v10H5z", "M12 15v2"],
  menu: ["M4 7h16", "M4 12h16", "M4 17h16"],
  search: ["m21 21-4.35-4.35", "M10.8 18a7.2 7.2 0 1 0 0-14.4 7.2 7.2 0 0 0 0 14.4Z"],
  shield: ["M12 3 20 6v5c0 5.2-3.45 8.5-8 10-4.55-1.5-8-4.8-8-10V6l8-3Z", "m8.5 12 2.2 2.2 4.8-4.8"],
  spark: ["m12 3-1.5 6.5L4 11l6.5 1.5L12 19l1.5-6.5L20 11l-6.5-1.5L12 3Z"],
  warning: ["M12 3 2.5 20h19L12 3Z", "M12 9v4", "M12 17h.01"],
};

export function Icon({ name, label }: { readonly name: IconName; readonly label?: string }) {
  return (
    <svg aria-hidden={label === undefined} aria-label={label} className="icon" fill="none" viewBox="0 0 24 24">
      {iconPaths[name].map((path) => (
        <path d={path} key={path} />
      ))}
    </svg>
  );
}
