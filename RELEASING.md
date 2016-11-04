# Releasing a new version
1. (Optional) Update the libcalico-go pin to the latest release in glide.yaml and run `glide up -v`
2. Choose a version e.g. `export VERSION=v1.0.0`
3. Create a tag e.g. `git tag $VERSION`
4. Get a clean run of the STs `make clean st`
5. Check that the version number is reporting correctly `dist/libnetwork-plugin -v`
6. Push the images to the container repositories `make release`
7. Push the tag e.g. `git push origin $VERSION`
8. Create a release on Github, using the tag which was just pushed.
