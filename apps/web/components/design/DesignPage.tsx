"use client";

import {
  ActionsRow,
  Button,
  Checkbox,
  EmptyState,
  ErrorNotice,
  Experts,
  Field,
  Input,
  Player,
  RadioGroup,
  RecentStrip,
  Segmented,
  Select,
  Slider,
  Stage,
  Stepper,
  Textarea,
  appearsHere,
  makeLabel,
  makingLabel,
} from "@wasifyai/ui";
import { ImageIcon, PencilIcon, SaveIcon } from "lucide-react";
import { type ReactNode, useState } from "react";

const VOICES = [
  {
    label: "Built in",
    options: [
      { value: "heart", label: "Heart", hint: "warm, female" },
      { value: "sky", label: "Sky", hint: "bright, female" },
      { value: "adam", label: "Adam", hint: "deep, male" },
    ],
  },
  { label: "Your voices", options: [{ value: "mine", label: "My narrator", hint: "cloned" }] },
];

const noop = () => {};
const cover = (hue: number) => (
  <span
    aria-hidden="true"
    className="block size-full"
    style={{
      background: `linear-gradient(135deg, oklch(70% 0.12 ${hue}), oklch(45% 0.14 ${hue + 40}))`,
    }}
  />
);

function Section({ title, text, children }: { title: string; text: string; children: ReactNode }) {
  return (
    <section className="grid gap-4" aria-label={title}>
      <header className="grid gap-1">
        <h2 className="m-0 font-semibold text-lg">{title}</h2>
        <p className="m-0 text-muted-foreground text-sm">{text}</p>
      </header>
      {children}
    </section>
  );
}

function Example({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 rounded-lg border bg-surface p-4">
      <span className="font-medium text-muted-foreground text-xs uppercase tracking-wider">
        {label}
      </span>
      {children}
    </div>
  );
}

/** The foundation of the one make screen (ADR-0093, stage U1), each piece in each of its states. */
export function DesignPage() {
  const [voice, setVoice] = useState<string | undefined>("heart");
  const [keep, setKeep] = useState(true);
  const [whose, setWhose] = useState("me");
  const [length, setLength] = useState(30);
  const [mode, setMode] = useState("create");
  const [step, setStep] = useState(1);
  const actions = [
    { label: "Edit this", onSelect: noop, icon: <PencilIcon aria-hidden="true" /> },
    { label: "Save a copy", onSelect: noop, icon: <SaveIcon aria-hidden="true" /> },
    { label: "Make again", onSelect: noop },
    { label: "Use as reference", onSelect: noop },
    { label: "Rename", onSelect: noop },
    { label: "Delete", onSelect: noop, destructive: true },
  ];
  const recent = [200, 260, 320, 30, 90, 150].map((hue, i) => ({
    id: String(i),
    cover: cover(hue),
    label: `Picture ${i + 1}`,
    onOpen: noop,
    current: i === 0,
  }));

  return (
    <div className="grid gap-10" data-design>
      <header className="grid gap-2">
        <h1 className="m-0 font-semibold text-2xl">Design</h1>
        <p className="m-0 max-w-prose text-muted-foreground">
          The shared components of Wasify AI in every state, in the theme you are in. A stage of the
          UI plan is checked against this page before a screen changes.
        </p>
      </header>

      <Section title="Words" text="One verb and one noun per thing a person makes (words.ts).">
        <Example label="Labels">
          <div className="flex flex-wrap gap-2">
            <Button type="button">{makeLabel("picture")}</Button>
            <Button type="button">{makeLabel("song")}</Button>
            <Button type="button">{makeLabel("model3d")}</Button>
            <Button type="button" variant="outline" disabled>
              {makingLabel("video")}
            </Button>
          </div>
        </Example>
      </Section>

      <Section
        title="Field"
        text="A label, the control, one hint line, and the error when there is one."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Example label="Default">
            <Field label="Name" hint="Short is best.">
              {({ id, describedBy }) => (
                <Input id={id} aria-describedby={describedBy} placeholder="Ena" />
              )}
            </Field>
          </Example>
          <Example label="Optional, filled">
            <Field label="Title" optional>
              {({ id }) => <Input id={id} defaultValue="A lighthouse at sunrise" />}
            </Field>
          </Example>
          <Example label="Error">
            <Field label="Magic word" error="Use one word, letters only.">
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  defaultValue="my word"
                />
              )}
            </Field>
          </Example>
          <Example label="Text">
            <Field label="What should it say?" hint="Press ⌘ + Enter to make it.">
              {({ id, describedBy }) => (
                <Textarea
                  id={id}
                  aria-describedby={describedBy}
                  rows={3}
                  placeholder="Good evening, and welcome."
                />
              )}
            </Field>
          </Example>
          <Example label="Disabled">
            <Field label="Seed">
              {({ id }) => <Input id={id} disabled placeholder="the model's own choice" />}
            </Field>
          </Example>
        </div>
      </Section>

      <Section title="Select" text="Pick one of many, with groups and a second line per option.">
        <div className="grid gap-4 md:grid-cols-3">
          <Example label="With groups">
            <Select aria-label="Voice" value={voice} onValueChange={setVoice} options={VOICES} />
          </Example>
          <Example label="Nothing chosen">
            <Select
              aria-label="Language"
              value={undefined}
              onValueChange={noop}
              placeholder="Choose a language…"
              options={[
                { value: "en", label: "English" },
                { value: "bn", label: "Bengali" },
              ]}
            />
          </Example>
          <Example label="Disabled">
            <Select
              aria-label="Recording"
              value="a"
              onValueChange={noop}
              disabled
              options={[{ value: "a", label: "Hello, how are you?" }]}
            />
          </Example>
        </div>
      </Section>

      <Section
        title="Checkbox and RadioGroup"
        text="A yes or no; one of a few, with a line under each."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Example label="Checkbox">
            <div className="grid gap-3">
              <Checkbox
                checked={keep}
                onCheckedChange={setKeep}
                label="Keep the music and sounds behind the voice"
              />
              <Checkbox
                checked={false}
                onCheckedChange={noop}
                label="No singing (instrumental)"
                hint="Words are ignored."
              />
              <Checkbox
                checked={true}
                onCheckedChange={noop}
                label="Look for models when the app starts"
                disabled
              />
            </div>
          </Example>
          <Example label="RadioGroup">
            <RadioGroup
              label="Whose picture is this?"
              value={whose}
              onValueChange={setWhose}
              options={[
                {
                  value: "art",
                  label: "A drawing, painting or other artwork",
                  hint: "not a photograph of a person",
                },
                { value: "me", label: "A picture of me" },
                { value: "other", label: "Someone who has given me permission" },
              ]}
            />
          </Example>
          <Example label="RadioGroup, disabled">
            <RadioGroup
              label="Search service"
              value="ddg"
              onValueChange={noop}
              disabled
              options={[
                { value: "ddg", label: "DuckDuckGo" },
                { value: "brave", label: "Brave Search", hint: "needs your key" },
              ]}
            />
          </Example>
        </div>
      </Section>

      <Section
        title="Slider and Segmented"
        text="A number said in words; one of a few side by side."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Example label="Slider">
            <Slider
              label="Length"
              value={length}
              min={5}
              max={240}
              step={5}
              onValueChange={setLength}
              format={(v) => `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`}
            />
          </Example>
          <Example label="Slider, disabled">
            <Slider
              label="Speed"
              value={1}
              min={0.5}
              max={2}
              step={0.1}
              onValueChange={noop}
              disabled
              format={(v) => `${v.toFixed(1)}×`}
            />
          </Example>
          <Example label="Segmented">
            <div className="grid gap-3">
              <Segmented
                label="Mode"
                value={mode}
                onValueChange={setMode}
                options={[
                  { value: "create", label: "Create" },
                  { value: "edit", label: "Edit" },
                  { value: "inpaint", label: "Inpaint" },
                  { value: "reference", label: "Reference" },
                ]}
              />
              <Segmented
                label="Shape"
                size="sm"
                value="landscape"
                onValueChange={noop}
                options={[
                  { value: "landscape", label: "Landscape 3:2" },
                  { value: "portrait", label: "Portrait 2:3" },
                  { value: "square", label: "Square", disabled: true },
                ]}
              />
            </div>
          </Example>
        </div>
      </Section>

      <Section
        title="Stepper and Experts"
        text="Where a person is in a flow; the settings only an expert needs, closed."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Example label="Stepper">
            <div className="grid gap-3">
              <Stepper steps={["Add pictures", "Check", "Teach"]} current={step} onStep={setStep} />
              <Stepper steps={["Recording", "Language", "Script", "Make"]} current={3} />
            </div>
          </Example>
          <Example label="Experts">
            <div className="grid gap-3">
              <Experts summary="seed, tempo, key">
                <Field label="Seed">
                  {({ id }) => <Input id={id} placeholder="the model's own choice" />}
                </Field>
              </Experts>
              <Experts open title="For experts" summary="open">
                <Field label="Tempo" hint="Beats per minute, 30 to 300.">
                  {({ id, describedBy }) => (
                    <Input id={id} aria-describedby={describedBy} placeholder="120" />
                  )}
                </Field>
              </Experts>
            </div>
          </Example>
        </div>
      </Section>

      <Section
        title="EmptyState and ErrorNotice"
        text="What goes here and the first step; what happened, in plain words, never a path."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Example label="EmptyState">
            <EmptyState
              icon={ImageIcon}
              title={appearsHere("picture")}
              text="Describe it on the left, then press Make the picture."
              action={
                <Button type="button" variant="outline">
                  Try an example
                </Button>
              }
            />
          </Example>
          <Example label="EmptyState, small">
            <EmptyState
              size="sm"
              title="No voices of your own yet."
              text="Describe one or clone one from a short recording."
            />
          </Example>
          <Example label="ErrorNotice">
            <ErrorNotice
              message="not mocked: GET /products/wasifyai-video/status"
              next="Start the engine, then try again."
              onRetry={noop}
              onReset={noop}
            />
          </Example>
          <Example label="ErrorNotice, plain">
            <ErrorNotice
              title="That file is too large"
              message="That file is too large. Use one under 300 MB."
            />
          </Example>
        </div>
      </Section>

      <Section title="ActionsRow and Player" text="Three actions and a menu; the app's own player.">
        <div className="grid gap-4 md:grid-cols-2">
          <Example label="ActionsRow">
            <div className="grid gap-3">
              <ActionsRow actions={actions} />
              <ActionsRow actions={actions.slice(0, 2)} size="default" />
            </div>
          </Example>
          <Example label="Player">
            <div className="grid gap-3">
              <Player
                src="data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA="
                title="Hello, how are you?"
                duration={62}
                actions={
                  <Button type="button" size="sm" variant="ghost">
                    Save
                  </Button>
                }
              />
            </div>
          </Example>
        </div>
      </Section>

      <Section title="Stage" text="Where the result appears: empty, working, error, result.">
        <div className="grid gap-4 md:grid-cols-2">
          <Example label="Empty">
            <Stage
              minHeight="min-h-[14rem]"
              state={{
                kind: "empty",
                icon: ImageIcon,
                title: appearsHere("picture"),
                text: "Describe it, then press Make the picture.",
              }}
            />
          </Example>
          <Example label="Working">
            <Stage
              minHeight="min-h-[14rem]"
              state={{
                kind: "working",
                label: makingLabel("picture"),
                text: "About 20 seconds; it took 24 last time.",
                value: 0.45,
                onStop: noop,
              }}
            />
          </Example>
          <Example label="Error">
            <Stage
              minHeight="min-h-[14rem]"
              state={{
                kind: "error",
                message: "Error: the image engine stopped (HTTP 502)",
                onRetry: noop,
                onReset: noop,
              }}
            />
          </Example>
          <Example label="Result">
            <Stage
              state={{
                kind: "result",
                children: (
                  <div className="aspect-[3/2] w-full max-w-sm overflow-hidden rounded-md">
                    {cover(230)}
                  </div>
                ),
                caption: "A lighthouse on a cliff at sunrise · 1024 × 683 · 24 s",
                actions,
              }}
            />
          </Example>
        </div>
      </Section>

      <Section
        title="RecentStrip"
        text="The last things this tool made, with See all to the Library."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Example label="Items">
            <RecentStrip items={recent} onSeeAll={noop} />
          </Example>
          <Example label="Loading">
            <RecentStrip items={[]} loading onSeeAll={noop} />
          </Example>
          <Example label="Empty">
            <RecentStrip items={[]} onSeeAll={noop} />
          </Example>
        </div>
      </Section>
    </div>
  );
}
