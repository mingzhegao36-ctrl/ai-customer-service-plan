<script setup lang="ts">
import {
  MessageSquare, History, Bot, PlugZap, ChartNoAxesCombined, ListTodo, Settings2,
  BookOpen, Headphones, FlaskConical, Plus, ArrowUp, ArrowRight, ChevronRight, ChevronDown,
  Search, Menu, X, MoreHorizontal, Check, Copy, ThumbsUp, ThumbsDown, RotateCcw,
  Square, LoaderCircle, CircleHelp, ArrowUpRight, ShieldCheck, FileText, Download,
  Trash2, CircleCheck, Clock3, CircleAlert, LogOut, SlidersHorizontal, Sparkles,
  Layers, CalendarDays, LockKeyhole, Ban, Play, PanelRightClose, LayoutDashboard,
  Command, CornerDownLeft, CircleDot, ArrowLeft,
} from '@lucide/vue'
withDefaults(defineProps<{ name: string; size?: number; stroke?: number }>(), { size: 18, stroke: 1.7 })
const icons: Record<string, unknown> = {
  chat: MessageSquare, history: History, bot: Bot, plug: PlugZap, chart: ChartNoAxesCombined,
  tasks: ListTodo, settings: Settings2, book: BookOpen, headset: Headphones, flask: FlaskConical,
  plus: Plus, send: ArrowUp, arrow: ArrowRight, chevron: ChevronRight, down: ChevronDown,
  search: Search, menu: Menu, close: X, more: MoreHorizontal, check: Check, copy: Copy,
  like: ThumbsUp, dislike: ThumbsDown, retry: RotateCcw, stop: Square, loading: LoaderCircle,
  help: CircleHelp, external: ArrowUpRight, shield: ShieldCheck, file: FileText, download: Download,
  trash: Trash2, success: CircleCheck, clock: Clock3, alert: CircleAlert, logout: LogOut,
  sliders: SlidersHorizontal, sparkle: Sparkles, layers: Layers, calendar: CalendarDays,
  lock: LockKeyhole, ban: Ban, play: Play, collapse: PanelRightClose,
  overview: LayoutDashboard, command: Command, enter: CornerDownLeft, activity: CircleDot, back: ArrowLeft,
}
</script>
<template><component :is="icons[name] || icons.chat" :size="size" :stroke-width="stroke" aria-hidden="true" /></template>
