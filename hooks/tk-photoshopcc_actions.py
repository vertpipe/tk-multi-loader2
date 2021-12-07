# Copyright (c) 2015 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Hook that loads defines all the available actions, broken down by publish type.
"""

import os
import re

import sgtk
from sgtk.platform.qt import QtGui
from tank_vendor import six

HookBaseClass = sgtk.get_hook_baseclass()

# Name of available actions. Corresponds to both the environment config values and the action instance names.
_ADD_AS_A_LAYER = "add_as_a_layer"
_OPEN_FILE = "open_file"


class PhotoshopActions(HookBaseClass):

    ##############################################################################################################
    # public interface - to be overridden by deriving classes

    def generate_actions(self, sg_publish_data, actions, ui_area):
        """
        Returns a list of action instances for a particular publish.
        This method is called each time a user clicks a publish somewhere in the UI.
        The data returned from this hook will be used to populate the actions menu for a publish.

        The mapping between Publish types and actions are kept in a different place
        (in the configuration) so at the point when this hook is called, the loader app
        has already established *which* actions are appropriate for this object.

        The hook should return at least one action for each item passed in via the
        actions parameter.

        This method needs to return detailed data for those actions, in the form of a list
        of dictionaries, each with name, params, caption and description keys.

        Because you are operating on a particular publish, you may tailor the output
        (caption, tooltip etc) to contain custom information suitable for this publish.

        The ui_area parameter is a string and indicates where the publish is to be shown.
        - If it will be shown in the main browsing area, "main" is passed.
        - If it will be shown in the details area, "details" is passed.
        - If it will be shown in the history area, "history" is passed.

        Please note that it is perfectly possible to create more than one action "instance" for
        an action! You can for example do scene introspection - if the action passed in
        is "character_attachment" you may for example scan the scene, figure out all the nodes
        where this object can be attached and return a list of action instances:
        "attach to left hand", "attach to right hand" etc. In this case, when more than
        one object is returned for an action, use the params key to pass additional
        data into the run_action hook.

        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        :param actions: List of action strings which have been defined in the app configuration.
        :param ui_area: String denoting the UI Area (see above).
        :returns List of dictionaries, each with keys name, params, caption and description
        """
        app = self.parent
        app.log_debug(
            "Generate actions called for UI element %s. "
            "Actions: %s. Publish Data: %s" % (ui_area, actions, sg_publish_data)
        )

        action_instances = []

        if _ADD_AS_A_LAYER in actions:
            action_instances.append(
                {
                    "name": _ADD_AS_A_LAYER,
                    "params": None,
                    "caption": "Add as a Layer",
                    "description": "Adds a layer referencing the image to the current document.",
                }
            )

        if _OPEN_FILE in actions:
            action_instances.append(
                {
                    "name": _OPEN_FILE,
                    "params": None,
                    "caption": "Open File",
                    "description": "This will open the file.",
                }
            )

        return action_instances

    def execute_multiple_actions(self, actions):
        """
        Executes the specified action on a list of items.

        The default implementation dispatches each item from ``actions`` to
        the ``execute_action`` method.

        The ``actions`` is a list of dictionaries holding all the actions to
        execute.

        Each entry will have the following values:

            name: Name of the action to execute
            sg_publish_data: Publish information coming from Shotgun
            params: Parameters passed down from the generate_actions hook.

        .. note::
            This is the default entry point for the hook. It reuses the
            ``execute_action`` method for backward compatibility with hooks
            written for the previous version of the loader.

        .. note::
            The hook will stop applying the actions on the selection if an error
            is raised midway through.

        :param list actions: Action dictionaries.
        """
        for single_action in actions:
            name = single_action["name"]
            sg_publish_data = single_action["sg_publish_data"]
            params = single_action["params"]
            self.execute_action(name, params, sg_publish_data)

    def execute_action(self, name, params, sg_publish_data):
        """
        Execute a given action. The data sent to this be method will
        represent one of the actions enumerated by the generate_actions method.

        :param name: Action name string representing one of the items returned
                     by generate_actions.
        :param params: Params data, as specified by generate_actions.
        :param sg_publish_data: Shotgun data dictionary with all the standard
                                publish fields.
        """
        app = self.parent
        app.log_debug(
            "Execute action called for action %s. "
            "Parameters: %s. Publish Data: %s" % (name, params, sg_publish_data)
        )

        # resolve path
        # toolkit uses utf-8 encoded strings internally and the Photoshop API expects unicode
        # so convert the path to ensure filenames containing complex characters are supported
        path = six.ensure_text(self.get_publish_path(sg_publish_data))

        # Check for image sequence, and search first frame
        if "%" in path:
            folder = os.path.dirname(path)

            frame_sequences = self.__get_frame_sequences(folder)

            frame_sequence = frame_sequences[0]
            first_frame = int(min(frame_sequence[1]))

            path = path % first_frame

        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)

        if name == _OPEN_FILE:
            self._open_file(path, sg_publish_data)
        if name == _ADD_AS_A_LAYER:
            self._place_file(path, sg_publish_data)

    ###########################################################################
    # helper methods

    def _open_file(self, path, sg_publish_data):
        """
        Import contents of the given file into the scene.

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard
                                publish fields.
        """
        path = "/".join(path.split(os.path.sep))
        self.parent.log_debug("Opening file: %s" % path)
        file = self.parent.engine.adobe.File(path)
        self.parent.engine.adobe.app.load(file)

    def _place_file(self, path, sg_publish_data):
        """
        Import contents of the given file into the scene.

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard
                                publish fields.
        """
        path = "/".join(path.split(os.path.sep))
        adobe = self.parent.engine.adobe

        # We can't import in an empty scene.
        try:
            adobe.app.activeDocument
        except RuntimeError:
            QtGui.QMessageBox.warning(
                None,
                "Add To Layer",
                "Please open a document first.",
            )
            return

        # When File->Place'ing a PSD on top of another, here's what the Script Listener generates.
        # (Download at http://helpx.adobe.com/photoshop/kb/plug-ins-photoshop-cs61.html#id_68969)
        # // =======================================================
        #     var idPlc = charIDToTypeID("Plc ");
        #     var placeActionDesc = new ActionDescriptor();
        #     var idnull = charIDToTypeID("null");
        #     placeActionDesc.putPath( idnull, new File("/Users/boismej/Documents/1.psd") );
        #     var idFTcs = charIDToTypeID("FTcs");
        #     var idQCSt = charIDToTypeID("QCSt");
        #     var idQcsa = charIDToTypeID("Qcsa");
        #     placeActionDesc.putEnumerated( idFTcs, idQCSt, idQcsa );
        #     // ... I have omitted the transform parameters. We'll take the defaults for now.
        # executeAction( idPlc, placeActionDesc, DialogModes.NO );

        action_desc = adobe.ActionDescriptor()
        action_desc.putPath(adobe.charIDToTypeID("null"), adobe.File(path))

        # We're using the charIDs here, which are illegible. Included right
        # after is the string name of the ID, though even that isn't much
        # use in most cases.
        #
        # Not sure why these are set, but they are mandatory and seem to be
        # transform related. Omitting them makes the Place action fail, even
        # if we don't specify a transform. These flags seem to be poorly
        # documented and code samples found on the web using the Place action
        # use them without any mention as to what they mean.
        action_desc.putEnumerated(
            adobe.charIDToTypeID("FTcs"),  # freeTransformCenterState
            adobe.charIDToTypeID("QCSt"),  # quadCenterState
            adobe.charIDToTypeID("Qcsa"),  # QCSAverage
        )

        # Everything is setup. Adds the layer to the document.
        adobe.executeAction(
            adobe.charIDToTypeID("Plc "),  # placeEvent
            action_desc,
            adobe.DialogModes.NO,
        )

    @staticmethod
    def __get_frame_sequences(folder, extensions=None, frame_spec=None):
        """
        Copied from the publisher plugin, and customized to return file sequences with frame lists instead of filenames
        Given a folder, inspect the contained files to find what appear to be
        files with frame numbers.
        :param folder: The path to a folder potentially containing a sequence of
            files.
        :param extensions: A list of file extensions to retrieve paths for.
            If not supplied, the extension will be ignored.
        :param frame_spec: A string to use to represent the frame number in the
            return sequence path.
        :return: A list of tuples for each identified frame sequence. The first
            item in the tuple is a sequence path with the frame number replaced
            with the supplied frame specification. If no frame spec is supplied,
            a python string format spec will be returned with the padding found
            in the file.
            Example::
            get_frame_sequences(
                "/path/to/the/folder",
                ["exr", "jpg"],
                frame_spec="{FRAME}"
            )
            [
                (
                    "/path/to/the/supplied/folder/key_light1.{FRAME}.exr",
                    [<frame_1_framenumber>, <frame_2_framenumber>, ...]
                ),
                (
                    "/path/to/the/supplied/folder/fill_light1.{FRAME}.jpg",
                    [<frame_1_framenumber>, <frame_2_framenumber>, ...]
                )
            ]
        """
        FRAME_REGEX = re.compile(r"(.*)([._-])(\d+)\.([^.]+)$", re.IGNORECASE)

        # list of already processed file names
        processed_names = {}

        # examine the files in the folder
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)

            if os.path.isdir(file_path):
                # ignore subfolders
                continue

            # see if there is a frame number
            frame_pattern_match = re.search(FRAME_REGEX, filename)

            if not frame_pattern_match:
                # no frame number detected. carry on.
                continue

            prefix = frame_pattern_match.group(1)
            frame_sep = frame_pattern_match.group(2)
            frame_str = frame_pattern_match.group(3)
            extension = frame_pattern_match.group(4) or ""

            # filename without a frame number.
            file_no_frame = "%s.%s" % (prefix, extension)

            if file_no_frame in processed_names:
                # already processed this sequence. add the framenumber to the list, later we can use this to determine the framerange
                processed_names[file_no_frame]["frame_list"].append(frame_str)
                continue

            if extensions and extension not in extensions:
                # not one of the extensions supplied
                continue

            # make sure we maintain the same padding
            if not frame_spec:
                padding = len(frame_str)
                frame_spec = "%%0%dd" % (padding,)

            seq_filename = "%s%s%s" % (prefix, frame_sep, frame_spec)

            if extension:
                seq_filename = "%s.%s" % (seq_filename, extension)

            # build the path in the same folder
            seq_path = os.path.join(folder, seq_filename)

            # remember each seq path identified and a list of files matching the
            # seq pattern
            processed_names[file_no_frame] = {
                "sequence_path": seq_path,
                "frame_list": [frame_str],
            }

        # build the final list of sequence paths to return
        frame_sequences = []
        for file_no_frame in processed_names:

            seq_info = processed_names[file_no_frame]
            seq_path = seq_info["sequence_path"]

            frame_sequences.append((seq_path, seq_info["frame_list"]))

        return frame_sequences
