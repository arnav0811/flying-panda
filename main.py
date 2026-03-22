import sys
import os
import json
import time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from crime_schema import generate_crime_schema
from red_herrings import inject_red_herrings
from meta_controller import SuspenseController
from plot_generator import generate_plot_point
from story_compiler import compile_story, generate_crime_story

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def save_tension_curve(controller, plot_points, filepath):
    fig, ax = plt.subplots(figsize=(12, 5))

    # Actual tension
    x_actual = list(range(len(controller.tension_history)))
    ax.plot(x_actual, controller.tension_history, "o-", color="#e74c3c",
            linewidth=2, markersize=6, label="Actual Tension", zorder=3)

    # Target curve (offset by 1 since tension_history includes initial 0)
    x_target = list(range(1, len(controller.target_curve) + 1))
    ax.plot(x_target, controller.target_curve, "--", color="#95a5a6",
            linewidth=1.5, label="Target Curve", alpha=0.7)

    # Mark event types with colors
    type_colors = {
        "clue_discovery": "#2ecc71",
        "red_herring_encounter": "#f39c12",
        "false_lead": "#9b59b6",
        "obstacle": "#e67e22",
        "suspect_confrontation": "#3498db",
        "criminal_interference": "#e74c3c",
        "breakthrough": "#1abc9c",
        "resolution": "#2c3e50",
    }

    for pp in plot_points:
        color = type_colors.get(pp.event_type, "#7f8c8d")
        ax.annotate(pp.title[:20], (pp.number, pp.tension_level),
                    fontsize=6, rotation=30, ha="left", va="bottom",
                    color=color, alpha=0.8)

    # Formatting
    ax.set_xlabel("Plot Point")
    ax.set_ylabel("Tension Level")
    ax.set_title("Suspense Tension Curve")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Add act dividers
    n = len(plot_points)
    if n > 0:
        ax.axvline(x=n * 0.25, color="#bdc3c7", linestyle=":", alpha=0.5)
        ax.axvline(x=n * 0.75, color="#bdc3c7", linestyle=":", alpha=0.5)
        ax.text(n * 0.12, 1.0, "Act 1", ha="center", fontsize=9, color="#7f8c8d")
        ax.text(n * 0.50, 1.0, "Act 2", ha="center", fontsize=9, color="#7f8c8d")
        ax.text(n * 0.87, 1.0, "Act 3", ha="center", fontsize=9, color="#7f8c8d")

    plt.tight_layout()
    plt.savefig(filepath, dpi=150)
    plt.close()


def run(setting, num_suspects=4):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    print("=" * 60)
    print("  FLYING PANDA - Murder Mystery Generator")
    print("  CS 7634 - AI Storytelling in Virtual Worlds")
    print("=" * 60)

    # Step 1: Generate Crime Schema
    print(f"\n[1/6] Generating crime schema for setting: {setting}...")
    schema = generate_crime_schema(setting, num_suspects)
    print(f"  Victim: {schema.victim}")
    print(f"  Criminal: {schema.criminal_name}")
    print(f"  Suspects: {', '.join(s.name for s in schema.suspects)}")
    print(f"  Evidence chain: {len(schema.evidence_chain)} clues")

    # Step 2: Inject Red Herrings
    print("\n[2/6] Injecting red herrings...")
    schema = inject_red_herrings(schema)
    print(f"  Added {len(schema.red_herrings)} red herrings:")
    for rh in schema.red_herrings:
        print(f"    - {rh.description} (fragility: {rh.fragility})")

    # Save the crime schema
    schema_path = os.path.join(OUTPUT_DIR, f"crime_schema_{timestamp}.json")
    with open(schema_path, "w") as f:
        f.write(schema.to_json())
    print(f"\n  Crime schema saved: {schema_path}")

    # Step 3: Generate crime backstory
    print("\n[3/6] Generating the crime backstory...")
    crime_story = generate_crime_story(schema)

    # Step 4: Run the meta-controller loop
    print("\n[4/6] Running suspense meta-controller...")
    controller = SuspenseController(schema, num_plot_points=16)
    plot_points = []

    while not controller.is_done():
        spec = controller.next_plot_point_spec()
        if spec is None:
            break

        print(f"  Generating plot point {spec.point_number}: "
              f"{spec.event_type}/{spec.subtype} "
              f"(target tension: {spec.target_tension:.2f})...")

        pp = generate_plot_point(schema, spec, plot_points)
        controller.update_state(pp)
        plot_points.append(pp)

        print(f"    -> \"{pp.title}\" (tension: {pp.tension_level:.2f})")

    print(f"\n  Generated {len(plot_points)} plot points.")
    print(f"  Final tension: {controller.current_tension:.2f}")
    print(f"  Clues revealed: {len(controller.revealed_clues)}/{len(schema.evidence_chain)}")

    # Step 5: Compile final story
    print("\n[5/6] Compiling final story...")
    final_story = compile_story(schema, plot_points)

    # Step 6: Save everything
    print("\n[6/6] Saving outputs...")

    # Save tension curve plot
    curve_path = os.path.join(OUTPUT_DIR, f"tension_curve_{timestamp}.png")
    save_tension_curve(controller, plot_points, curve_path)
    print(f"  Tension curve: {curve_path}")

    # Save the full output file
    output_path = os.path.join(OUTPUT_DIR, f"mystery_{timestamp}.txt")
    with open(output_path, "w") as f:
        f.write("=" * 70 + "\n")
        f.write("  FLYING PANDA - Generated Murder Mystery\n")
        f.write(f"  Setting: {setting}\n")
        f.write(f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")

        f.write("PART I: THE CRIME (What Actually Happened)\n")
        f.write("-" * 50 + "\n\n")
        f.write(crime_story + "\n\n")

        f.write("=" * 70 + "\n")
        f.write("PART II: THE INVESTIGATION (The Solving Story)\n")
        f.write("-" * 50 + "\n\n")

        f.write(f"Total Plot Points: {len(plot_points)}\n\n")

        # Plot point summary table
        f.write("PLOT POINT SUMMARY:\n")
        f.write("-" * 50 + "\n")
        for pp in plot_points:
            f.write(f"  {pp.number:2d}. [{pp.event_type:25s}] {pp.title} "
                    f"(tension: {pp.tension_level:.2f})\n")
        f.write("\n" + "=" * 70 + "\n\n")

        f.write("FULL STORY:\n")
        f.write("-" * 50 + "\n\n")
        f.write(final_story + "\n")

    print(f"  Full story: {output_path}")

    # Save raw plot points as JSON for analysis
    raw_path = os.path.join(OUTPUT_DIR, f"plot_points_{timestamp}.json")
    with open(raw_path, "w") as f:
        json.dump([pp.to_dict() for pp in plot_points], f, indent=2)
    print(f"  Raw plot points: {raw_path}")

    print("\n" + "=" * 60)
    print("  Done! Your mystery has been generated.")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        setting = " ".join(sys.argv[1:])
    else:
        setting = "a prestigious university research lab"

    run(setting)
