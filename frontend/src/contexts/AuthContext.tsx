"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { fetchApi } from "@/lib/api";

interface User {
  id: string;
  username: string;
  account_status: string;
  must_change_password: boolean;
  role_names: string[];
}

interface Company {
  id: string;
  name: string;
  slug: string;
}

interface AuthState {
  user: User | null;
  company: Company | null;
  permissions: string[];
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  checkAuth: () => Promise<User | null>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    company: null,
    permissions: [],
    isLoading: true,
  });

  const checkAuth = async () => {
    try {
      const data = await fetchApi("/auth/me");
      if (data && data.user) {
        setState({ user: data.user, company: data.company, permissions: data.permissions || [], isLoading: false });
        return data.user as User;
      } else {
        setState({ user: null, company: null, permissions: [], isLoading: false });
        return null;
      }
    } catch {
      setState({ user: null, company: null, permissions: [], isLoading: false });
      return null;
    }
  };

  const logout = async () => {
    try {
      await fetchApi("/auth/logout", {
        method: "POST",
        body: JSON.stringify({}),
      });
    } catch (e) {
      console.error(e);
    }
    setState({ user: null, company: null, permissions: [], isLoading: false });
  };

  useEffect(() => {
    let cancelled = false;
    fetchApi("/auth/me")
      .then((data) => {
        if (!cancelled) {
          if (data && data.user) {
            setState({ user: data.user, company: data.company, permissions: data.permissions || [], isLoading: false });
          } else {
            setState({ user: null, company: null, permissions: [], isLoading: false });
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ user: null, company: null, permissions: [], isLoading: false });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, checkAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
