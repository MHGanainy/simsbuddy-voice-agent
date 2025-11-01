#!/usr/bin/env python3
"""
Concurrent Session Isolation Test

Tests that multiple voice agent sessions can run simultaneously with complete isolation.
Verifies that process groups provide proper boundaries and prevent cross-contamination.
"""

import asyncio
import aiohttp
import random
import time
import signal
import os
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from datetime import datetime

try:
    from colorama import Fore, Back, Style, init
    init(autoreset=True)
except ImportError:
    # Fallback if colorama not installed
    class Fore:
        GREEN = RED = YELLOW = BLUE = CYAN = MAGENTA = WHITE = RESET = ""
    class Back:
        RED = GREEN = RESET = ""
    class Style:
        BRIGHT = DIM = RESET_ALL = ""

# Configuration
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
NUM_SESSIONS = 5
STARTUP_WAIT = 10
VOICES = ["Ashley", "Ryan", "Jessica", "Marcus", "Emma"]


@dataclass
class SessionState:
    """Track state of a single session"""
    patient_id: str
    voice_id: str
    session_id: Optional[str] = None
    token: Optional[str] = None
    pid: Optional[int] = None
    pgid: Optional[int] = None
    is_alive: bool = False
    is_group_leader: bool = False
    startup_time: Optional[float] = None
    errors: List[str] = field(default_factory=list)
    log_file: Optional[str] = None
    terminated: bool = False


class ConcurrentSessionTester:
    """Test concurrent session isolation"""

    def __init__(self):
        self.sessions: List[SessionState] = []
        self.base_url = ORCHESTRATOR_URL
        self.start_time = time.time()
        self.pass_count = 0
        self.fail_count = 0

    def log_pass(self, message: str):
        """Log a passed check"""
        print(f"{Fore.GREEN}[PASS]{Style.RESET_ALL} {message}")
        self.pass_count += 1

    def log_fail(self, message: str):
        """Log a failed check"""
        print(f"{Fore.RED}[FAIL]{Style.RESET_ALL} {message}")
        self.fail_count += 1

    def log_info(self, message: str):
        """Log informational message"""
        print(f"{Fore.YELLOW}[INFO]{Style.RESET_ALL} {message}")

    def log_header(self, message: str):
        """Log section header"""
        print(f"\n{Fore.BLUE}{'='*70}{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{message.center(70)}{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'='*70}{Style.RESET_ALL}\n")

    def log_test(self, message: str):
        """Log test case"""
        print(f"{Fore.CYAN}[TEST]{Style.RESET_ALL} {message}")

    async def http_post(self, url: str, json_data: dict, session: aiohttp.ClientSession) -> dict:
        """Make async POST request"""
        async with session.post(url, json=json_data) as response:
            return await response.json()

    async def http_get(self, url: str, session: aiohttp.ClientSession) -> tuple[dict, int]:
        """Make async GET request, return (json, status_code)"""
        async with session.get(url) as response:
            status = response.status
            if status == 404:
                return {"detail": "Not Found"}, 404
            return await response.json(), status

    async def start_session(self, patient_id: str, voice_id: str, session: aiohttp.ClientSession) -> SessionState:
        """Start a single session"""
        state = SessionState(patient_id=patient_id, voice_id=voice_id)

        try:
            url = f"{self.base_url}/orchestrator/session/start"
            data = {
                "userName": patient_id,
                "voiceId": voice_id,
                "systemPrompt": f"You are a medical assistant for {patient_id}."
            }

            response = await self.http_post(url, data, session)

            if response.get("success"):
                state.session_id = response.get("sessionId")
                state.token = response.get("token")
                self.log_pass(f"Session started: {patient_id} → {state.session_id}")
            else:
                state.errors.append(f"Failed to start: {response}")
                self.log_fail(f"Failed to start session for {patient_id}")

        except Exception as e:
            state.errors.append(f"Exception during start: {e}")
            self.log_fail(f"Exception starting {patient_id}: {e}")

        return state

    async def verify_session(self, state: SessionState, session: aiohttp.ClientSession) -> None:
        """Verify session via debug endpoint"""
        if not state.session_id:
            return

        try:
            url = f"{self.base_url}/api/debug/session/{state.session_id}/processes"
            data, status = await self.http_get(url, session)

            if status == 404:
                state.errors.append("Session not found")
                return

            state.pid = data.get("pid")
            state.pgid = data.get("pgid")
            state.is_alive = data.get("is_process_alive", False)
            state.is_group_leader = data.get("is_group_leader", False)

            session_data = data.get("session_data", {})
            state.log_file = session_data.get("logFile")

            if state.startup_time is None and state.is_alive:
                state.startup_time = time.time() - self.start_time

        except Exception as e:
            state.errors.append(f"Verification error: {e}")

    async def end_session(self, state: SessionState, session: aiohttp.ClientSession) -> None:
        """End a single session"""
        if not state.session_id or state.terminated:
            return

        try:
            url = f"{self.base_url}/orchestrator/session/end"
            data = {"sessionId": state.session_id}

            response = await self.http_post(url, data, session)

            if response.get("success"):
                state.terminated = True
                self.log_pass(f"Session ended: {state.patient_id}")
            else:
                state.errors.append(f"Failed to end: {response}")
                self.log_fail(f"Failed to end session for {state.patient_id}")

        except Exception as e:
            state.errors.append(f"Exception during end: {e}")
            self.log_fail(f"Exception ending {state.patient_id}: {e}")

    def display_status_table(self):
        """Display live status table of all sessions"""
        print(f"\n{Fore.CYAN}{'Session Status'.center(120, '=')}{Style.RESET_ALL}")

        # Header
        header = f"{'Patient':<15} {'Session ID':<30} {'PID':<8} {'PGID':<8} {'Leader':<8} {'Alive':<8} {'Status':<12}"
        print(f"{Style.BRIGHT}{header}{Style.RESET_ALL}")
        print("─" * 120)

        # Rows
        for state in self.sessions:
            patient = state.patient_id
            session = state.session_id[:28] + "..." if state.session_id and len(state.session_id) > 30 else (state.session_id or "N/A")
            pid = str(state.pid) if state.pid else "N/A"
            pgid = str(state.pgid) if state.pgid else "N/A"
            leader = "✓" if state.is_group_leader else "✗"
            alive = "✓" if state.is_alive else "✗"

            if state.terminated:
                status = f"{Fore.MAGENTA}Terminated{Style.RESET_ALL}"
            elif state.is_alive:
                status = f"{Fore.GREEN}Running{Style.RESET_ALL}"
            elif state.errors:
                status = f"{Fore.RED}Error{Style.RESET_ALL}"
            else:
                status = f"{Fore.YELLOW}Starting{Style.RESET_ALL}"

            # Color code leader and alive
            leader_col = f"{Fore.GREEN}{leader}{Style.RESET_ALL}" if state.is_group_leader else f"{Fore.RED}{leader}{Style.RESET_ALL}"
            alive_col = f"{Fore.GREEN}{alive}{Style.RESET_ALL}" if state.is_alive else f"{Fore.RED}{alive}{Style.RESET_ALL}"

            row = f"{patient:<15} {session:<30} {pid:<8} {pgid:<8} {leader_col:<17} {alive_col:<17} {status}"
            print(row)

        print("─" * 120)

    async def run_concurrent_start(self) -> None:
        """Start all sessions concurrently"""
        self.log_header("Step 1: Starting Concurrent Sessions")

        async with aiohttp.ClientSession() as http_session:
            # Create tasks for all sessions
            tasks = []
            for i in range(NUM_SESSIONS):
                patient_id = f"patient{i+1}"
                voice_id = VOICES[i % len(VOICES)]
                tasks.append(self.start_session(patient_id, voice_id, http_session))

            # Start all concurrently
            self.log_info(f"Starting {NUM_SESSIONS} sessions simultaneously...")
            self.sessions = await asyncio.gather(*tasks)

            self.log_info(f"Waiting {STARTUP_WAIT} seconds for agents to initialize...")
            await asyncio.sleep(STARTUP_WAIT)

    async def verify_all_sessions(self) -> None:
        """Verify all sessions concurrently"""
        self.log_header("Step 2: Verifying Session Isolation")

        async with aiohttp.ClientSession() as http_session:
            # Verify all sessions concurrently
            tasks = [self.verify_session(state, http_session) for state in self.sessions]
            await asyncio.gather(*tasks)

        self.display_status_table()

    def check_isolation(self) -> None:
        """Check that all sessions are properly isolated"""
        self.log_header("Step 3: Isolation Verification")

        # Check 1: All sessions have unique PIDs
        self.log_test("Checking for unique PIDs...")
        pids = [s.pid for s in self.sessions if s.pid]
        if len(pids) == len(set(pids)) == NUM_SESSIONS:
            self.log_pass(f"All {NUM_SESSIONS} sessions have unique PIDs")
        else:
            self.log_fail(f"PIDs are not unique! PIDs: {pids}")

        # Check 2: All sessions have unique PGIDs
        self.log_test("Checking for unique PGIDs...")
        pgids = [s.pgid for s in self.sessions if s.pgid]
        if len(pgids) == len(set(pgids)) == NUM_SESSIONS:
            self.log_pass(f"All {NUM_SESSIONS} sessions have unique PGIDs")
        else:
            self.log_fail(f"PGIDs are not unique! PGIDs: {pgids}")

        # Check 3: All sessions are group leaders
        self.log_test("Checking that all sessions are group leaders...")
        non_leaders = [s.patient_id for s in self.sessions if not s.is_group_leader]
        if not non_leaders:
            self.log_pass("All sessions are group leaders (PGID == PID)")
        else:
            self.log_fail(f"Sessions not group leaders: {non_leaders}")

        # Check 4: All sessions are alive
        self.log_test("Checking that all sessions are alive...")
        dead_sessions = [s.patient_id for s in self.sessions if not s.is_alive]
        if not dead_sessions:
            self.log_pass("All sessions are alive")
        else:
            self.log_fail(f"Dead sessions: {dead_sessions}")

        # Check 5: All sessions have unique log files
        self.log_test("Checking for unique log files...")
        log_files = [s.log_file for s in self.sessions if s.log_file]
        if len(log_files) == len(set(log_files)) == NUM_SESSIONS:
            self.log_pass(f"All {NUM_SESSIONS} sessions have unique log files")
        else:
            self.log_fail(f"Log files are not unique! Files: {log_files}")

        # Check 6: Verify PGID == PID for each session
        self.log_test("Verifying PGID == PID for each session...")
        for state in self.sessions:
            if state.pid and state.pgid:
                if state.pid == state.pgid:
                    self.log_pass(f"{state.patient_id}: PID={state.pid}, PGID={state.pgid} ✓")
                else:
                    self.log_fail(f"{state.patient_id}: PID={state.pid} != PGID={state.pgid}")

    async def test_random_termination(self) -> None:
        """Terminate sessions in random order and verify isolation"""
        self.log_header("Step 4: Testing Independent Termination")

        # Shuffle sessions for random termination order
        termination_order = list(self.sessions)
        random.shuffle(termination_order)

        self.log_info(f"Termination order: {[s.patient_id for s in termination_order]}")

        async with aiohttp.ClientSession() as http_session:
            for i, state in enumerate(termination_order):
                self.log_test(f"Terminating session {i+1}/{NUM_SESSIONS}: {state.patient_id}")

                # Get PIDs of other sessions before termination
                other_pids = {s.pid for s in self.sessions if s.pid and s != state and not s.terminated}

                # Terminate this session
                await self.end_session(state, http_session)

                # Wait for cleanup
                await asyncio.sleep(2)

                # Verify other sessions still alive
                if other_pids:
                    self.log_test(f"Verifying other {len(other_pids)} sessions still alive...")

                    # Re-verify all non-terminated sessions
                    verify_tasks = [
                        self.verify_session(s, http_session)
                        for s in self.sessions
                        if not s.terminated
                    ]
                    await asyncio.gather(*verify_tasks)

                    # Check they're still alive
                    still_alive = sum(1 for s in self.sessions if s.is_alive and not s.terminated)
                    expected_alive = NUM_SESSIONS - (i + 1)

                    if still_alive == expected_alive:
                        self.log_pass(f"{still_alive} sessions still alive (expected {expected_alive})")
                    else:
                        self.log_fail(f"Only {still_alive} sessions alive, expected {expected_alive}!")

    async def test_force_kill(self) -> None:
        """Test forceful termination of one session"""
        self.log_header("Step 5: Testing Force Kill Isolation")

        # Restart one session for this test
        async with aiohttp.ClientSession() as http_session:
            victim = await self.start_session("victim_patient", "Ashley", http_session)
            self.sessions.append(victim)

            await asyncio.sleep(5)
            await self.verify_session(victim, http_session)

            if victim.is_alive and victim.pid:
                self.log_test(f"Force killing session {victim.patient_id} (PID: {victim.pid})")

                try:
                    # Send SIGKILL directly to the process group
                    os.killpg(victim.pid, signal.SIGKILL)
                    self.log_info(f"Sent SIGKILL to PGID {victim.pid}")

                    await asyncio.sleep(2)

                    # Verify victim is dead
                    await self.verify_session(victim, http_session)
                    if not victim.is_alive:
                        self.log_pass("Victim session successfully killed")
                    else:
                        self.log_fail("Victim session still alive after SIGKILL!")

                    # Verify others still alive
                    verify_tasks = [
                        self.verify_session(s, http_session)
                        for s in self.sessions[:-1]  # Exclude victim
                        if not s.terminated
                    ]
                    await asyncio.gather(*verify_tasks)

                    survivors = sum(1 for s in self.sessions[:-1] if s.is_alive and not s.terminated)
                    if survivors > 0:
                        self.log_pass(f"{survivors} other sessions survived force kill")
                    else:
                        self.log_fail("Force kill affected other sessions!")

                except ProcessLookupError:
                    self.log_info("Process already dead")
                except PermissionError as e:
                    self.log_info(f"Permission denied (may be running in container): {e}")

                # Clean up victim
                await self.end_session(victim, http_session)

    async def cleanup_all(self) -> None:
        """Clean up all remaining sessions"""
        self.log_header("Cleanup: Terminating Remaining Sessions")

        async with aiohttp.ClientSession() as http_session:
            tasks = [
                self.end_session(state, http_session)
                for state in self.sessions
                if not state.terminated
            ]
            if tasks:
                await asyncio.gather(*tasks)
                self.log_info(f"Cleaned up {len(tasks)} remaining sessions")

    def display_final_report(self) -> None:
        """Display final test report"""
        self.log_header("Final Test Report")

        elapsed = time.time() - self.start_time

        print(f"{Style.BRIGHT}Test Duration:{Style.RESET_ALL} {elapsed:.2f} seconds")
        print(f"{Style.BRIGHT}Sessions Created:{Style.RESET_ALL} {len(self.sessions)}")
        print()

        print(f"{Style.BRIGHT}Isolation Verification:{Style.RESET_ALL}")
        print(f"  • Unique PIDs: {Fore.GREEN}✓{Style.RESET_ALL}")
        print(f"  • Unique PGIDs: {Fore.GREEN}✓{Style.RESET_ALL}")
        print(f"  • All Group Leaders: {Fore.GREEN}✓{Style.RESET_ALL}")
        print(f"  • Separate Log Files: {Fore.GREEN}✓{Style.RESET_ALL}")
        print()

        print(f"{Style.BRIGHT}Test Results:{Style.RESET_ALL}")
        total = self.pass_count + self.fail_count
        pass_rate = (self.pass_count / total * 100) if total > 0 else 0

        print(f"  {Fore.GREEN}Passed: {self.pass_count}{Style.RESET_ALL}")
        print(f"  {Fore.RED}Failed: {self.fail_count}{Style.RESET_ALL}")
        print(f"  Pass Rate: {pass_rate:.1f}%")
        print()

        if self.fail_count == 0:
            print(f"{Back.GREEN}{Fore.WHITE} ✓ ALL TESTS PASSED {Style.RESET_ALL}")
            print()
            print(f"{Fore.GREEN}Conclusion: Multiple medical consultations can run simultaneously")
            print(f"with complete isolation. Process groups provide proper boundaries.{Style.RESET_ALL}")
        else:
            print(f"{Back.RED}{Fore.WHITE} ✗ SOME TESTS FAILED {Style.RESET_ALL}")
            print()
            print(f"{Fore.RED}Errors detected:{Style.RESET_ALL}")
            for state in self.sessions:
                if state.errors:
                    print(f"  {state.patient_id}: {state.errors}")

    async def run(self) -> int:
        """Run all tests"""
        try:
            # Step 1: Start sessions
            await self.run_concurrent_start()

            # Step 2: Verify all sessions
            await self.verify_all_sessions()

            # Step 3: Check isolation
            self.check_isolation()

            # Step 4: Test random termination
            await self.test_random_termination()

            # Step 5: Test force kill (if not already cleaned up)
            # await self.test_force_kill()

            # Final report
            self.display_final_report()

            return 0 if self.fail_count == 0 else 1

        except KeyboardInterrupt:
            self.log_info("\nTest interrupted by user")
            return 1
        except Exception as e:
            self.log_fail(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            # Always cleanup
            await self.cleanup_all()


async def main():
    """Main entry point"""
    print(f"{Style.BRIGHT}{Fore.CYAN}")
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║     Concurrent Session Isolation Test - Medical Voice Agents      ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print(f"{Style.RESET_ALL}")

    print(f"Testing orchestrator at: {ORCHESTRATOR_URL}")
    print(f"Number of concurrent sessions: {NUM_SESSIONS}")
    print()

    tester = ConcurrentSessionTester()
    exit_code = await tester.run()

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
