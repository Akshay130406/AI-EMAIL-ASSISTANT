export type MailFolder = "inbox" | "sent" | "drafts";

export interface DemoEmail {
  id: string;
  sender: string;
  initials: string;
  address: string;
  to: string;
  subject: string;
  preview: string;
  body: string;
  time: string;
  category: "Primary" | "Updates" | "Promotions";
  unread: boolean;
  starred: boolean;
  priority: "High" | "Normal";
  folder: MailFolder;
}
