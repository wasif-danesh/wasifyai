"use client";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import type { LanguageChoice, VoiceCatalog, VoiceChoice } from "@wasifyai/contracts";
import { Loader2 } from "lucide-react";
import type { KeyboardEvent } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

export const MAX_TEXT = 2000;
const GENDERS = [
  { id: "female", label: "Female" },
  { id: "male", label: "Male" },
] as const;

const EXAMPLES: Record<string, string> = {
  "en-US": "Welcome to our shop. We are open from nine to five, Monday to Saturday.",
  "en-GB": "Good evening, and welcome to tonight's programme.",
  bn: "আমাদের দোকানে আপনাকে স্বাগতম। আমরা সোমবার থেকে শনিবার পর্যন্ত খোলা থাকি।",
  es: "Bienvenidos a nuestra tienda. Estamos abiertos de lunes a sábado.",
  fr: "Bienvenue dans notre boutique. Nous sommes ouverts du lundi au samedi.",
  hi: "हमारी दुकान में आपका स्वागत है। हम सोमवार से शनिवार तक खुले हैं।",
  it: "Benvenuti nel nostro negozio. Siamo aperti dal lunedì al sabato.",
  "pt-BR": "Bem-vindos à nossa loja. Abrimos de segunda a sábado.",
};

export type SpeechFormValue = {
  text: string;
  language: string;
  gender: string;
  voice?: string;
};

const schema = z.object({
  text: z
    .string()
    .trim()
    .min(1, "Type the words you want spoken.")
    .max(MAX_TEXT, `Please keep it to ${MAX_TEXT} characters or fewer.`),
  language: z.string().min(1),
  gender: z.string().min(1),
  voice: z.string().optional(),
});
type Values = z.infer<typeof schema>;

/** The voices a language has for one gender (an empty list is a gap, shown as such). */
function voicesOf(lang: LanguageChoice | undefined, gender: string): VoiceChoice[] {
  return (lang?.genders as Record<string, VoiceChoice[]> | undefined)?.[gender] ?? [];
}

export function SpeechForm({
  catalog,
  onSubmit,
  initial,
  busy = false,
}: {
  catalog: VoiceCatalog;
  onSubmit: (value: SpeechFormValue) => void;
  initial?: Partial<SpeechFormValue>;
  busy?: boolean;
}) {
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    mode: "onSubmit",
    defaultValues: {
      text: initial?.text ?? "",
      language: initial?.language ?? catalog.languages[0]?.id ?? "",
      gender: initial?.gender ?? "female",
      voice: initial?.voice,
    },
  });
  const { language, gender, voice, text } = form.watch();
  const lang = catalog.languages.find((l) => l.id === language);
  const options = voicesOf(lang, gender);
  const chosen = options.find((v) => v.id === voice) ?? options.find((v) => v.default);
  const canSubmit = text.trim().length > 0 && options.length > 0 && !busy;

  function pickLanguage(next: string) {
    const l = catalog.languages.find((x) => x.id === next);
    form.setValue("language", next);
    form.setValue("voice", undefined);
    // keep the gender if the new language has it; otherwise move to the one it has
    if (voicesOf(l, gender).length === 0) {
      const other = GENDERS.find((g) => voicesOf(l, g.id).length > 0);
      if (other) form.setValue("gender", other.id);
    }
  }

  const send = form.handleSubmit((values) => {
    if (options.length === 0 || busy) return;
    onSubmit({
      text: values.text,
      language: values.language,
      gender: values.gender,
      ...(values.voice ? { voice: values.voice } : {}),
    });
  });

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send();
  }

  return (
    <Form {...form}>
      <form onSubmit={send} className={cn(panel, "gap-6")} noValidate aria-busy={busy || undefined}>
        <FormField
          control={form.control}
          name="text"
          render={({ field }) => (
            <FormItem>
              <FormLabel>What should it say?</FormLabel>
              <FormControl>
                <Textarea
                  {...field}
                  onKeyDown={onKey}
                  placeholder={EXAMPLES[language] ?? EXAMPLES["en-US"]}
                  rows={5}
                  lang={lang?.id}
                  className="min-h-32 text-base"
                />
              </FormControl>
              <div className="flex flex-wrap items-center gap-2">
                <FormDescription className="basis-full sm:grow sm:basis-auto">
                  Write it in the language you chose. Press Ctrl or ⌘ + Enter to start.
                </FormDescription>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    form.setValue("text", EXAMPLES[language] ?? EXAMPLES["en-US"] ?? "", {
                      shouldValidate: true,
                    })
                  }
                >
                  Use an example
                </Button>
                <span
                  className={`text-sm tabular-nums ${text.length > MAX_TEXT * 0.9 ? "text-destructive" : "text-muted-foreground"}`}
                >
                  {text.length}/{MAX_TEXT}
                </span>
              </div>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="language"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Language</FormLabel>
              <Select value={field.value} onValueChange={pickLanguage}>
                <FormControl>
                  <SelectTrigger className="w-full sm:w-72">
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {catalog.languages.map((l) => (
                    <SelectItem key={l.id} value={l.id} lang={l.id}>
                      {l.name === l.english ? l.name : `${l.name} · ${l.english}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="gender"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Voice</FormLabel>
              <RadioGroup
                value={field.value}
                onValueChange={(v) => {
                  field.onChange(v);
                  form.setValue("voice", undefined);
                }}
                className="flex flex-wrap gap-2"
                aria-label="Male or female voice"
              >
                {GENDERS.map((g) => {
                  const disabled = voicesOf(lang, g.id).length === 0;
                  return (
                    <label
                      key={g.id}
                      htmlFor={`gender-${g.id}`}
                      className="flex cursor-pointer items-center gap-2 rounded-md border bg-card px-4 py-2 text-sm has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent has-[[data-disabled]]:cursor-not-allowed has-[[data-disabled]]:opacity-50"
                    >
                      <RadioGroupItem id={`gender-${g.id}`} value={g.id} disabled={disabled} />
                      {g.label}
                    </label>
                  );
                })}
              </RadioGroup>
              {options.length === 0 ? (
                <FormDescription aria-live="polite">
                  There is no {gender} voice for {lang?.english ?? "this language"} yet.
                </FormDescription>
              ) : null}
              {options.length > 1 ? (
                <div className="pt-1">
                  <Select value={chosen?.id} onValueChange={(v) => form.setValue("voice", v)}>
                    <SelectTrigger className="w-full sm:w-72" aria-label="Which voice">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((v) => (
                        <SelectItem key={v.id} value={v.id}>
                          {v.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
              {chosen?.quality === "limited" ? (
                <FormDescription aria-live="polite">
                  Voices for this language are still limited and may sound less natural.
                </FormDescription>
              ) : null}
            </FormItem>
          )}
        />

        <div className="flex flex-wrap items-center gap-4">
          <Button type="submit" size="lg" disabled={!canSubmit}>
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            Create speech
          </Button>
          <span className="text-sm text-muted-foreground">
            {language === "bn" ? "Bengali takes a little longer." : "Takes a few seconds."}
          </span>
        </div>
      </form>
    </Form>
  );
}
