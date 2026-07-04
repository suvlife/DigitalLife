#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 /tmp/togospace preset JSON 配置文件的完整性与一致性。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path("/tmp/togospace")
RT_DIR = ROOT / "assets/preset/role_templates"
TEAMS_DIR = ROOT / "assets/preset/teams"

# 本次新增/修改的 21 个角色模板（按 mtime 19:xx on Jul 4 识别 + 用户声明）
NEW_ROLE_TEMPLATES = [
    "buffett_master.json",
    "graham_master.json",
    "fisher_master.json",
    "lynch_master.json",
    "livermore_master.json",
    "oneil_master.json",
    "schwartz_master.json",
    "simons_master.json",
    "dalio_master.json",
    "soros_master.json",
    "market_data_analyst.json",
    "market_intel.json",
    "bagua_fortune.json",
    "blind_school_master.json",
    "classics_scholar.json",
    "destiny_synthesizer.json",
    "dts_master.json",
    "meihua_master.json",
    "sizhu_analyst.json",
    "ziping_master.json",
    "ziwei_master.json",
]

results = []  # (check_id, status, detail)


def record(check_id, status, detail=""):
    results.append((check_id, status, detail))
    tag = "PASS" if status == "PASS" else "FAIL"
    print(f"[{tag}] {check_id}: {detail}" if detail else f"[{tag}] {check_id}")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. JSON 合法性：所有新增/修改的 JSON 文件都能被 json.load 解析
# ---------------------------------------------------------------------------
def check_json_validity():
    print("\n========== 1. JSON 合法性 ==========")
    files = (
        [RT_DIR / f for f in NEW_ROLE_TEMPLATES]
        + [TEAMS_DIR / "stock_analysis.json", TEAMS_DIR / "destiny_analysis.json"]
    )
    all_ok = True
    bad = []
    for p in files:
        if not p.exists():
            all_ok = False
            bad.append(f"{p.name} (NOT FOUND)")
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                json.load(f)
        except Exception as e:
            all_ok = False
            bad.append(f"{p.name}: {e}")
    record("1.json_validity", "PASS" if all_ok else "FAIL",
           "全部 %d 个文件 JSON 合法" % len(files) if all_ok else "解析失败: " + "; ".join(bad))


# ---------------------------------------------------------------------------
# 2. 角色模板格式：name / soul / i18n.display_name(zh-CN + en)；soul>200；name 与文件名对应
#    "name 与文件名对应" 的契约：name == 文件名 stem（去掉 .json）
#    依据：现有全部模板均满足（chief_investment_officer.json -> name='chief_investment_officer'），
#          且 runtime 通过 GtRoleTemplate.name 查询、模板以 name 入库，name 须稳定且可被
#          team JSON 的 role_template 字段精确引用。
# ---------------------------------------------------------------------------
def check_role_template_format():
    print("\n========== 2. 角色模板格式（21 个新模板）==========")
    problems = []
    for fname in NEW_ROLE_TEMPLATES:
        p = RT_DIR / fname
        if not p.exists():
            problems.append(f"{fname}: 文件不存在")
            continue
        try:
            d = load_json(p)
        except Exception as e:
            problems.append(f"{fname}: JSON 解析失败 {e}")
            continue

        # name
        name = d.get("name")
        if not name or not isinstance(name, str):
            problems.append(f"{fname}: 缺少 name 字段")
        else:
            stem = fname[:-5]  # strip .json
            if name != stem:
                problems.append(f"{fname}: name={name!r} 与文件名 stem={stem!r} 不一致")

        # soul
        soul = d.get("soul", "")
        if not soul or not isinstance(soul, str):
            problems.append(f"{fname}: 缺少 soul 字段")
        elif len(soul) <= 200:
            problems.append(f"{fname}: soul 字数={len(soul)} <= 200")

        # i18n.display_name
        i18n = d.get("i18n", {})
        dn = i18n.get("display_name", {}) if isinstance(i18n, dict) else {}
        if not isinstance(dn, dict):
            problems.append(f"{fname}: i18n.display_name 不是对象")
        else:
            if "zh-CN" not in dn or not dn["zh-CN"]:
                problems.append(f"{fname}: 缺少 i18n.display_name.zh-CN")
            if "en" not in dn or not dn["en"]:
                problems.append(f"{fname}: 缺少 i18n.display_name.en")

    record("2.role_template_format", "PASS" if not problems else "FAIL",
           "21 个新模板格式全部合规" if not problems else "\n  - " + "\n  - ".join(problems))


# ---------------------------------------------------------------------------
# 通用：团队一致性检查
# ---------------------------------------------------------------------------
def check_team_consistency(team_path, team_label, expected_uuid, expected_agent_count=None):
    print(f"\n========== {team_label} 一致性 ==========")
    try:
        data = load_json(team_path)
    except Exception as e:
        record(f"{team_label}.load", "FAIL", f"无法加载: {e}")
        return

    # UUID
    uuid = data.get("uuid")
    record(f"{team_label}.uuid", "PASS" if uuid == expected_uuid else "FAIL",
           f"uuid={uuid!r} (期望 {expected_uuid!r})")

    agents = data.get("agents", [])
    agent_names = [a.get("name") for a in agents if isinstance(a, dict)]
    agent_name_set = set(agent_names)

    # agent count
    if expected_agent_count is not None:
        record(f"{team_label}.agent_count", "PASS" if len(agents) == expected_agent_count else "FAIL",
               f"agents 数量={len(agents)} (期望 {expected_agent_count})")

    # role_template 引用文件存在
    rt_files = {f.name for f in RT_DIR.glob("*.json")}
    missing_rt = []
    for a in agents:
        rt = a.get("role_template")
        if not rt:
            missing_rt.append(f"{a.get('name')}: 无 role_template")
            continue
        if f"{rt}.json" not in rt_files:
            missing_rt.append(f"{a.get('name')}: role_template={rt} 无对应文件 {rt}.json")
    record(f"{team_label}.role_template_files", "PASS" if not missing_rt else "FAIL",
           "所有 role_template 都有对应文件" if not missing_rt else "\n  - " + "\n  - ".join(missing_rt))

    # dept_tree 检查
    dept = data.get("dept_tree")
    dept_problems = []

    def walk_dept(node, is_root, parent_agents):
        if not isinstance(node, dict):
            dept_problems.append("dept_tree 节点非对象")
            return
        node_agents = node.get("agents", []) or []
        node_manager = node.get("manager")
        node_name = node.get("dept_name", "<unnamed>")
        # 每个部门 agents 列表 >= 2
        if len(node_agents) < 2:
            dept_problems.append(f"部门 {node_name}: agents 数量={len(node_agents)} < 2")
        # 所有 agent name 在 agents 数组中已定义
        for an in node_agents:
            if an not in agent_name_set:
                dept_problems.append(f"部门 {node_name}: agent {an!r} 未在 agents 数组定义")
        # manager 在本部门 agents 列表中
        if node_manager and node_manager not in node_agents:
            dept_problems.append(f"部门 {node_name}: manager={node_manager!r} 不在本部门 agents 列表中")
        # 子部门的 manager 在父部门的 agents 列表中
        children = node.get("children", []) or []
        for ch in children:
            ch_manager = ch.get("manager") if isinstance(ch, dict) else None
            if ch_manager and ch_manager not in node_agents:
                dept_problems.append(
                    f"子部门 {ch.get('dept_name','?')} 的 manager={ch_manager!r} 不在父部门 {node_name} 的 agents 列表中")
            walk_dept(ch, False, node_agents)

    walk_dept(dept, True, None)

    # 收集 dept_tree 中出现的所有 agent
    dept_agent_refs = set()

    def collect_dept_agents(node):
        if not isinstance(node, dict):
            return
        for an in (node.get("agents") or []):
            dept_agent_refs.add(an)
        for ch in (node.get("children") or []):
            collect_dept_agents(ch)

    collect_dept_agents(dept)

    record(f"{team_label}.dept_tree", "PASS" if not dept_problems else "FAIL",
           "dept_tree 结构合规" if not dept_problems else "\n  - " + "\n  - ".join(dept_problems))

    # preset_rooms agents 引用检查（OPERATOR 除外）
    rooms = data.get("preset_rooms", [])
    room_problems = []
    for r in rooms:
        rname = r.get("name", "<unnamed>")
        for an in r.get("agents", []):
            if an == "OPERATOR":
                continue
            if an not in agent_name_set:
                room_problems.append(f"房间 {rname}: agent {an!r} 未在 agents 数组定义")
    record(f"{team_label}.preset_rooms_refs", "PASS" if not room_problems else "FAIL",
           "所有 preset_rooms 成员引用正确（OPERATOR 除外）" if not room_problems else "\n  - " + "\n  - ".join(room_problems))

    return {
        "agent_names": agent_name_set,
        "dept_agent_refs": dept_agent_refs,
        "agents": agents,
        "rooms": rooms,
    }


# ---------------------------------------------------------------------------
# 3. stock_analysis.json 一致性 + 9 Agent 全部在 dept_tree（destiny）
# ---------------------------------------------------------------------------
def check_stock_uuid_v2():
    # UUID v2 — 单独强调
    print("\n========== 3. stock_analysis.json UUID v2 ==========")
    data = load_json(TEAMS_DIR / "stock_analysis.json")
    uuid = data.get("uuid", "")
    record("3.stock_uuid_v2", "PASS" if "v2" in uuid else "FAIL", f"uuid={uuid!r}")


def check_destiny_extra():
    print("\n========== 4. destiny_analysis.json 额外检查 ==========")
    data = load_json(TEAMS_DIR / "destiny_analysis.json")
    agents = data.get("agents", [])
    agent_names = set(a.get("name") for a in agents)

    # 9 个 Agent 全部在 dept_tree 中出现
    dept = data.get("dept_tree", {})
    dept_refs = set()

    def collect(node):
        if not isinstance(node, dict):
            return
        for an in (node.get("agents") or []):
            dept_refs.add(an)
        for ch in (node.get("children") or []):
            collect(ch)

    collect(dept)
    not_in_dept = agent_names - dept_refs
    record("4.destiny_9agents_in_dept", "PASS" if not not_in_dept else "FAIL",
           "9 个 Agent 全部在 dept_tree 出现" if not not_in_dept else
           "未在 dept_tree 出现: " + ", ".join(sorted(not_in_dept)))

    # 5 个预设房间的成员引用正确
    rooms = data.get("preset_rooms", [])
    record("4.destiny_5rooms", "PASS" if len(rooms) == 5 else "FAIL",
           f"预设房间数={len(rooms)} (期望 5)")


# ---------------------------------------------------------------------------
# 5. 角色模板 name 唯一性（全局）
# ---------------------------------------------------------------------------
def check_role_template_name_uniqueness():
    print("\n========== 5. 角色模板 name 全局唯一性 ==========")
    names = {}
    dups = []
    for f in sorted(RT_DIR.glob("*.json")):
        try:
            d = load_json(f)
        except Exception:
            continue
        n = d.get("name")
        names.setdefault(n, []).append(f.name)
    for n, files in names.items():
        if len(files) > 1:
            dups.append(f"name={n!r}: {files}")
    record("5.role_template_name_unique", "PASS" if not dups else "FAIL",
           "所有 role_templates name 全局唯一" if not dups else "\n  - " + "\n  - ".join(dups))


# ---------------------------------------------------------------------------
# 6. 引用完整性（字面）：两个团队引用的 role_template 都能在目录找到对应文件
#    即 role_templates/{role_template}.json 存在
# ---------------------------------------------------------------------------
def check_reference_integrity():
    print("\n========== 6. 引用完整性（role_template -> 文件存在）==========")
    problems = []
    for team_file in ["stock_analysis.json", "destiny_analysis.json"]:
        data = load_json(TEAMS_DIR / team_file)
        for a in data.get("agents", []):
            rt = a.get("role_template")
            aname = a.get("name")
            if not rt:
                problems.append(f"{team_file}: agent {aname}: 无 role_template")
                continue
            if not (RT_DIR / f"{rt}.json").exists():
                problems.append(f"{team_file}: agent {aname}: role_template={rt} 无对应文件 {rt}.json")
    record("6.reference_integrity", "PASS" if not problems else "FAIL",
           "两个团队 role_template 引用的文件全部存在" if not problems else "\n  - " + "\n  - ".join(problems))


# ---------------------------------------------------------------------------
# 6b. [关键] 运行时名称解析一致性：agent.role_template 必须等于模板文件的 name 字段
#     依据：presetService._to_gt_agents 调用 get_role_template_by_name(agent.role_template)
#           按 GtRoleTemplate.name 查询；模板以 name=template.name 入库。
#     若不一致 -> 查询返回 None -> Agent 被跳过 -> dept_tree 解析抛 DEPT_AGENT_NOT_FOUND
# ---------------------------------------------------------------------------
def check_runtime_name_resolution():
    print("\n========== 6b. [关键] 运行时名称解析一致性 ==========")
    print("  (契约: agent.role_template == 模板文件 name 字段)")
    problems = []
    for team_file in ["stock_analysis.json", "destiny_analysis.json"]:
        data = load_json(TEAMS_DIR / team_file)
        for a in data.get("agents", []):
            rt = a.get("role_template")
            aname = a.get("name")
            fpath = RT_DIR / f"{rt}.json"
            if not fpath.exists():
                problems.append(f"{team_file}: agent {aname}: 文件 {rt}.json 不存在")
                continue
            try:
                td = load_json(fpath)
            except Exception as e:
                problems.append(f"{team_file}: agent {aname}: 读取 {rt}.json 失败 {e}")
                continue
            tname = td.get("name")
            if tname != rt:
                problems.append(
                    f"{team_file}: agent {aname}: role_template={rt!r} != 文件 {rt}.json 的 name={tname!r}"
                    f"  -> 运行时 get_role_template_by_name({rt!r}) 返回 None，Agent 将被跳过")
    record("6b.runtime_name_resolution", "PASS" if not problems else "FAIL",
           "所有 agent.role_template 与模板 name 字段一致（运行时可解析）" if not problems else
           "\n  - " + "\n  - ".join(problems))


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def summary():
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    for cid, status, detail in results:
        tag = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{tag}] {cid}"
        if status == "FAIL":
            # 仅打印首行概要
            first = detail.split("\n")[0] if detail else ""
            line += f"  <- {first}"
        print(line)
    print("-" * 60)
    print(f"  总计: {passed} PASS / {failed} FAIL / {len(results)} 项")
    return 0 if failed == 0 else 1


def main():
    check_json_validity()
    check_role_template_format()
    # stock_analysis
    check_team_consistency(
        TEAMS_DIR / "stock_analysis.json",
        "3.stock",
        expected_uuid="preset-stock-analysis-v2",
        expected_agent_count=20,
    )
    check_stock_uuid_v2()
    # destiny_analysis
    check_team_consistency(
        TEAMS_DIR / "destiny_analysis.json",
        "4.destiny",
        expected_uuid="preset-destiny-analysis-v1",
        expected_agent_count=9,
    )
    check_destiny_extra()
    check_role_template_name_uniqueness()
    check_reference_integrity()
    check_runtime_name_resolution()
    sys.exit(summary())


if __name__ == "__main__":
    main()
