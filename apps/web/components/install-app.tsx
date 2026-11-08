"use client";

import { Check, Copy, Download } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { INSTALL_STEPS, type InstallPlatform, installPlatform } from "@/lib/install";

type InstallPrompt = Event & { prompt: () => Promise<void> };

/** Install instructions for the visitor's device. Shows nothing inside the installed app. */
export function InstallApp() {
  const [platform, setPlatform] = useState<InstallPlatform | null>(null);
  const [installed, setInstalled] = useState(false);
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  useEffect(() => {
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (navigator as Navigator & { standalone?: boolean }).standalone === true;
    setInstalled(standalone);
    setPlatform(installPlatform(navigator.userAgent, navigator.maxTouchPoints));

    const onPrompt = (e: Event) => {
      e.preventDefault(); // we show our own button instead of the browser's banner
      setPrompt(e as InstallPrompt);
    };
    const onInstalled = () => {
      setInstalled(true);
      setPrompt(null);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (installed || !platform) return null;
  const { title, steps } = INSTALL_STEPS[platform];

  async function install() {
    if (!prompt) return;
    await prompt.prompt();
    setPrompt(null); // a prompt can only be used once
  }

  async function copyLink() {
    // This page, wherever it's deployed. In-app browsers often block the clipboard, so say so.
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
    } catch {
      setCopyFailed(true);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-4 sm:p-5">
      <h3 className="text-xl leading-tight font-semibold">{prompt ? "Install SecurePitch" : title}</h3>
      {prompt ? (
        <>
          <p className="text-sm text-muted-foreground">
            Adds an icon to your device and opens full screen. Nothing financial is ever saved on
            the device.
          </p>
          <Button type="button" onClick={install} className="sm:self-start">
            <Download aria-hidden />
            Install the app
          </Button>
        </>
      ) : (
        <ol className="flex flex-col gap-2 text-sm">
          {steps.map((step, i) => (
            <li key={step} className="flex gap-2.5">
              <span
                aria-hidden
                className="grid size-5 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-foreground"
              >
                {i + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      )}
      {platform === "in-app" && (
        <Button type="button" variant="outline" onClick={copyLink} className="sm:self-start">
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? "Link copied" : "Copy the link"}
        </Button>
      )}
      {copyFailed && (
        <p className="text-sm [overflow-wrap:anywhere]">
          Couldn&apos;t copy it here. Open this address in your browser:{" "}
          <span className="font-mono">{window.location.href}</span>
        </p>
      )}
    </div>
  );
}
