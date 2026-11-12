export interface AuthenticatedUser {
  id: string;
  email: string;
  display_name: string | null;
  picture_url: string | null;
}

export interface AuthMeResponse {
  user: AuthenticatedUser;
  csrf_token: string;
}
