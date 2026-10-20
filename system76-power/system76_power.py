import subprocess
import time

class System76Power:
    perf_profiles = ['performance', 'balanced', 'battery']
    graphics_modes = ['nvidia', 'integrated', 'hybrid', 'compute']
    def __init__(self):
        result = subprocess.run(['system76-power', 'profile'], check=True, capture_output=True)
        output = result.stdout.decode(encoding="utf-8").split('\n')[0]
        self.performance = output.split(': ')[1].lower()
        self.graphics = None
        try:
            result = subprocess.run(['system76-power', 'graphics'], check=True, capture_output=True)
            self.graphics = result.stdout.decode(encoding="utf-8").split('\n')[0]
        except:
            pass

    def switchable(self):
        try:
            result = subprocess.run(['system76-power', 'graphics', 'switchable'], check=True, capture_output=True)
            output = result.stdout.decode(encoding="utf-8").strip()
            return output
        except subprocess.CalledProcessError as e:
            return e.stderr.decode(encoding="utf-8")

    def switch_perf_profile(self, profile = None):
        if not profile:
            idx = self.perf_profiles.index(self.performance)
            profile = self.perf_profiles[(idx + 1) % len(self.perf_profiles)]
        if self.performance == profile:
            return
        try:
            subprocess.run(['system76-power', 'profile', profile], check=True, capture_output=True)
            self.performance = profile
        except:
            pass

    def get_perf_profile(self):
        return self.performance

    def get_graphics_mode(self):
        return self.graphics

    def switch_graphics_mode(self, mode = None):
        if not mode:
            idx = self.graphics_modes.index(self.graphics)
            mode = self.graphics_modes[(idx + 1) % len(self.graphics_modes)]
        if self.graphics == mode or not self.graphics:
            return
        try:
            subprocess.run(['system76-power', 'graphics', mode], check=True, capture_output=True)
            self.graphics = mode
        except:
            pass

if __name__ == "__main__":
    transition_graph = {s: [target for target in System76Power.perf_profiles if target != s] for s in System76Power.perf_profiles}
    sys76_power = System76Power()
    stack = [sys76_power.get_perf_profile()]
    circuit = []

    while stack:
        current = stack[-1]
        if transition_graph[current]:
            next_state = transition_graph[current].pop()
            stack.append(next_state)
        else:
            circuit.append(stack.pop())

    sequence = circuit[::-1]

    from_profile = None
    for profile in sequence:
        if not from_profile:
            from_profile = profile
        if profile == sys76_power.get_perf_profile():
            continue
        print(f'Transition from {from_profile} to {profile}')
        sys76_power.switch_perf_profile(profile)
        from_profile = profile

    print(sys76_power.switchable())
