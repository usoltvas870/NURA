export interface TabItem {
  id: string;
  /** Tabler icon class, e.g. "ti-home-2" */
  icon: string;
  label: string;
  href: string;
}

export interface TabBarProps {
  /** ID of the currently active tab: "home" | "chat" | "tarot" | "profile" */
  active?: 'home' | 'chat' | 'tarot' | 'profile' | string;
  /**
   * Override the default 4-tab set. Default tabs:
   * home (Главная), chat (NURA), tarot (Практики), profile (Профиль)
   */
  tabs?: TabItem[];
}

export declare function TabBar(props: TabBarProps): JSX.Element;
