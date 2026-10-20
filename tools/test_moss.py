#!/usr/bin/env python3
"""Exercise MOSS's saved graph routing without loading GPU models."""
import json
import unittest
from pathlib import Path

GRAPH = Path(__file__).resolve().parents[1] / "workflows/MOSS Image/MOSS_Image_Workflow.json"


class MossRoutingTests(unittest.TestCase):
    def setUp(self):
        self.graph = json.loads(GRAPH.read_text())
        self.nodes = {node["id"]: node for node in self.graph["nodes"]}
        self.links = {link[0]: link for link in self.graph["links"]}

    def test_notes_are_markdown_and_prompts_are_connected(self):
        notes = [n for n in self.nodes.values() if n["type"] == "MarkdownNote"]
        self.assertEqual(len(notes), 2)
        for note in notes:
            self.assertFalse(note["inputs"])
            self.assertFalse(note["outputs"])
        encoders = [n for n in self.nodes.values() if n["type"] == "CLIPTextEncode"]
        self.assertEqual(len(encoders), 2)
        self.assertTrue(all(n["mode"] == 0 and n["inputs"][0]["link"] for n in encoders))

    def test_links_agree_with_both_endpoint_slots(self):
        for link_id, source, slot, target, target_slot, kind in self.links.values():
            self.assertIn(link_id, self.nodes[source]["outputs"][slot]["links"])
            self.assertEqual(self.nodes[target]["inputs"][target_slot]["link"], link_id)
            self.assertIn(self.nodes[target]["inputs"][target_slot]["type"], (kind, "*"))

    def test_toggle_routes_user_loras_to_only_the_selected_sampler(self):
        """Interpret only routing; sampler and weight operations are symbolic.

        ComfySwitchNode inputs are lazy: traverse only the chosen branch.
        Re-evaluate off/on/off to catch a graph wired to a fixed mode.
        """
        for enabled in (False, True, False):
            with self.subTest(kromoss=enabled):
                calls, cache = [], {}

                def evaluate(node_id, slot=0):
                    if node_id not in cache:
                        node = self.nodes[node_id]
                        kind = node["type"]
                        calls.append(kind)

                        def input_value(name):
                            item = next(i for i in node["inputs"] if i["name"] == name)
                            link = self.links[item["link"]]
                            return evaluate(link[1], link[2])

                        if kind == "PrimitiveBoolean":
                            result = (enabled,)
                        elif kind == "ComfySwitchNode":
                            result = (input_value("on_true" if input_value("switch") else "on_false"),)
                        elif kind == "UNETLoader":
                            result = ((node["widgets_values"][0],),)
                        elif kind == "LoraLoaderModelOnly":
                            result = (input_value("model") + (node["widgets_values"][0],),)
                        elif kind == "Power Lora Loader (rgthree)":
                            result = (input_value("model") + ("user-lora",), input_value("clip"))
                        elif kind == "KSampler":
                            result = ((input_value("model"), node["widgets_values"][2]),)
                            for name in ("positive", "negative", "latent_image"):
                                input_value(name)
                        elif kind == "VAEDecode":
                            result = (input_value("samples"),)
                            input_value("vae")
                        elif kind == "SaveImage":
                            result = (input_value("images"),)
                        elif kind == "CLIPTextEncode":
                            result = (input_value("clip"),)
                        elif kind in ("CLIPLoader", "VAELoader", "EmptyFlux2LatentImage"):
                            result = (kind,)
                        else:
                            self.fail(f"Unexpected executable node: {kind}")
                        cache[node_id] = result
                    return cache[node_id][slot]

                output = next(n for n in self.nodes.values() if n["type"] == "SaveImage")
                models, steps = evaluate(output["id"])
                expected = (
                    ("kromoss_int8_convrot.safetensors", "8-steps-dmd-lora.safetensors", "user-lora")
                    if enabled else ("moss_image_sft_int8_convrot.safetensors", "user-lora")
                )
                self.assertEqual(models, expected)
                self.assertEqual(steps, 8 if enabled else 25)
                self.assertEqual(calls.count("KSampler"), 1)
                self.assertEqual(calls.count("UNETLoader"), 1)
                self.assertEqual(calls.count("Power Lora Loader (rgthree)"), 1)


if __name__ == "__main__":
    unittest.main()
